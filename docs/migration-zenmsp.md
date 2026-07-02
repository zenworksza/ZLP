# ZenMSP: ZLF → ZLP Migration Plan

**Prepared by:** Claude (ZLP Architect)  
**Date:** 2026-07-02 (updated — OD-6 resolved, ionCube dropped)  
**Target:** ZenMSP on Laravel 13 / PHP 8.3

---

## 1. Overview

This plan migrates ZenMSP from its per-product ZLF implementation to ZLP. The migration is designed to be zero-downtime for existing customers and reversible at each stage.

**Key constraint:** Every customer install must have an active ZLP license before ZLF is removed. The cutover is per-install, not a fleet-wide flag flip.

---

## 2. Pre-migration Checklist (Vendor Side)

Before any customer migration begins:

- [ ] ZLP Authority deployed and accessible at `https://license.yourdomain.com`
- [ ] ZenMSP registered as a product: `slug=zenmsp`, plans match existing ZLF tiers
- [ ] ZenMSP plans seeded via `POST /dashboard/plans/seed/zenmsp` (starter / professional / enterprise)
- [ ] `zenplatform/zlf-php` package published to Satis at `https://packages.yourdomain.com`
- [ ] License keys generated for all active ZenMSP customers (see Section 3)
- [ ] Billing webhooks configured for active payment gateway (see Section 6)
- [ ] Rollback procedure reviewed (Section 8)

---

## 3. Key Generation

For each active ZenMSP customer, generate a ZLP license key via the vendor dashboard:

| ZLF plan | ZLP plan | Seats |
|---|---|---|
| Basic | starter | 1 |
| Professional | professional | seats from ZLF |
| Enterprise | enterprise | seats from ZLF |

Set `expires_at` to match the customer's current ZLF expiry. Set `customer_ref` to the customer's name/email.

Send each customer their `ZLP-XXXX-XXXX-XXXX` key with the activation instructions below.

---

## 4. SDK Installation (Per Customer Install)

### 4.1 Add Satis repository

In the customer's `composer.json`:

```json
{
  "repositories": [
    {
      "type": "composer",
      "url": "https://packages.yourdomain.com"
    }
  ],
  "config": {
    "bearer": {
      "packages.yourdomain.com": "REGISTRY_TOKEN_FROM_ACTIVATION"
    }
  }
}
```

### 4.2 Install the SDK

```bash
composer require zenplatform/zlf-php
```

### 4.3 Activate

```bash
php vendor/bin/zlp-agent activate
```

Follow the prompts. After activation:
- Token is written to `/var/lib/zlp/zenmsp/{install_id}.cache`
- `install.id` is written to `/var/lib/zlp/zenmsp/install.id`
- Customer receives env vars to set and a crontab line

Set the env vars in `.env`:
```
ZLP_INSTALL_ID=<from activation output>
ZLP_LICENSE_KEY=ZLP-XXXX-XXXX-XXXX
ZLP_PRODUCT=zenmsp
ZLP_DOMAIN=app.customer.com
ZLP_AUTHORITY_URL=https://license.yourdomain.com
```

---

## 5. ZenMSP Code Changes

### 5.1 Register the middleware (Laravel 13)

In `bootstrap/app.php`, add ZLP as a global middleware **before** any application middleware:

```php
use ZenPlatform\ZLF\LicenseMiddleware;

->withMiddleware(function (Middleware $middleware) {
    $middleware->prepend(function ($request, $next) {
        LicenseMiddleware::check('zenmsp');
        return $next($request);
    });
})
```

Or create a dedicated class:

```php
// app/Http/Middleware/ZlpLicense.php
namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use ZenPlatform\ZLF\LicenseMiddleware;

class ZlpLicense
{
    public function handle(Request $request, Closure $next): mixed
    {
        LicenseMiddleware::check('zenmsp');
        return $next($request);
    }
}
```

Register it globally:

```php
->withMiddleware(function (Middleware $middleware) {
    $middleware->prepend(\App\Http\Middleware\ZlpLicense::class);
})
```

### 5.2 Feature gates

Replace ZLF feature checks with ZLP:

```php
// Before (ZLF):
if (!$license->hasFeature('ms365')) { abort(402); }

// After (ZLP):
LicenseMiddleware::requireFeature('ms365');
```

Or using FeatureGate for conditional logic without aborting:

```php
use ZenPlatform\ZLF\FeatureGate;

if (FeatureGate::hasFeature((array) LicenseMiddleware::getToken(), 'ms365')) {
    // show MS365 UI
}
```

### 5.3 Heartbeat agent — Laravel scheduler

Instead of a raw crontab entry, add to `app/Console/Kernel.php` (or `routes/console.php` in Laravel 11+):

```php
// routes/console.php
Schedule::exec('php ' . base_path('vendor/bin/zlp-agent') . ' heartbeat')
    ->everyFifteenMinutes()
    ->appendOutputTo(storage_path('logs/zlp-agent.log'));
```

Ensure `php artisan schedule:run` is in the server crontab (standard for all Laravel installs):

```cron
* * * * * cd /path/to/zenmsp && php artisan schedule:run >> /dev/null 2>&1
```

### 5.4 Remove ZLF

Once ZLP is confirmed working on an install (at least one successful heartbeat logged in the ZLP dashboard), remove:
- ZLF composer package: `composer remove <old-zlf-package>`
- ZLF middleware registration
- ZLF feature check calls
- Any ZLF crontab entries

---

## 6. Billing Gateway Configuration

The ZLP Authority handles payment events from PayFast (ZAR) and PayPal (international) via webhooks. When a payment succeeds the license is automatically reinstated; when it fails the subscription moves to `overdue` and is suspended after a 24-hour grace period.

### 6.1 PayFast (primary — ZAR)

Set in `infra/.env` (or Docker secrets):
```
PAYFAST_MERCHANT_ID=<your merchant id>
PAYFAST_MERCHANT_KEY=<your merchant key>
PAYFAST_PASSPHRASE=<your passphrase>
PAYFAST_SANDBOX=false
```

In the PayFast merchant portal, configure the ITN (Instant Transaction Notification) URL:
```
https://license.yourdomain.com/v1/billing/payfast/webhook
```

For each customer subscription, set `m_payment_id` in the PayFast payment request to the `gateway_ref` stored in the `billing_subscriptions` table. This is how the webhook links a payment event back to a license key.

Create the subscription record via the dashboard API after the customer's first payment:
```
POST /dashboard/billing/subscriptions
{
  "license_key_id": "<uuid>",
  "gateway": "payfast",
  "gateway_ref": "<m_payment_id used in PayFast>"
}
```

### 6.2 PayPal (international)

Set in `infra/.env`:
```
PAYPAL_CLIENT_ID=<your client id>
PAYPAL_CLIENT_SECRET=<your client secret>
PAYPAL_WEBHOOK_ID=<webhook id from PayPal dashboard>
PAYPAL_SANDBOX=false
```

In the PayPal developer dashboard, register a webhook pointing to:
```
https://license.yourdomain.com/v1/billing/paypal/webhook
```

Subscribe to these event types:
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.DECLINED`
- `BILLING.SUBSCRIPTION.CANCELLED`

Set `custom_id` (or `reference_id`) on PayPal purchase units to the `gateway_ref` in the `billing_subscriptions` table.

### 6.3 Automated billing lifecycle

Once webhooks are configured, the following happens automatically:

| Event | Action |
|---|---|
| Payment success | Subscription → `active`, key reinstated if suspended |
| Payment failure | Subscription → `overdue`, `overdue_since` stamped |
| 24 h overdue | Scheduler suspends subscription + key → next heartbeat hard-blocks the install |
| Manual `mark-paid` in dashboard | Same as payment success — use for cash/EFT customers |
| Key approaching expiry (14 days) | Scheduler generates renewal invoice and emails customer |

---

## 7. Cutover Sequence

For each customer install, follow this sequence:

```
1. Install ZLP SDK via Composer
2. Run activation → verify install appears in ZLP dashboard
3. Add ZLP middleware to Laravel (shadow mode: both ZLF and ZLP active)
4. Verify first heartbeat succeeds (check ZLP dashboard → Install registry)
5. Remove ZLF middleware
6. Remove ZLF package + cleanup
7. Confirm customer can access ZenMSP (ZLP VALID state)
```

**Do not remove ZLF until step 4 is confirmed.** Running both in parallel for one heartbeat interval (15 min) is safe.

---

## 8. Rollback

If ZLP causes issues at any point before step 6:

1. Remove the `ZlpLicense` middleware from `bootstrap/app.php`
2. ZLF middleware resumes control
3. ZLP SDK can remain installed without side effects (it does nothing without middleware registration)

After step 6 (ZLF removed), rollback requires re-installing the ZLF package. Keep the old `composer.lock` for 30 days post-migration.

---

## 9. Post-Migration Validation

For each migrated install, verify in the ZLP vendor dashboard:

- [ ] Install status: **VALID**
- [ ] Last heartbeat: within the last 15 minutes
- [ ] No anomaly events
- [ ] Features in JWT match the customer's plan

Run a spot check: temporarily revoke the install via the dashboard → confirm customer sees HTTP 402 → un-revoke → confirm recovery on next heartbeat.

---

## 10. Timeline

| Week | Action |
|---|---|
| Week 1 | Deploy ZLP Authority to production, generate all customer keys |
| Week 2 | Pilot migration on 2–3 customers, validate full flow |
| Week 3–4 | Migrate remaining customers in batches of 10 |
| Week 5 | Remove ZLF from all installs, decommission ZLF infrastructure |

---

## 11. Open Items

All original open decisions affecting this migration are resolved:

| Decision | Resolution |
|---|---|
| **OD-4 ionCube** | Dropped — no obfuscation required. Security is enforced server-side via RS256 + HMAC. Customers install the plain SDK directly via Composer. |
| **OD-6 Billing gateway** | Resolved — PayFast ITN and PayPal webhook handlers are fully implemented in `authority/app/routers/billing.py`. Automatic suspension after 24-hour grace period is handled by the APScheduler job in `scheduler.py`. See Section 6 for configuration. |

No blockers remain for go-live.
