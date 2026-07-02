# ZLP PHP SDK Integration Guide

Package: `zenplatform/zlf-php`

---

## 1. Requirements

- PHP 8.1 or later (tested on 8.1, 8.2, 8.3 including CloudLinux/cPanel)
- Composer
- Cron access on the server (or Laravel scheduler)
- Writable directory for the token cache — default `/var/lib/zlp/`, override with `ZLP_CACHE_DIR`
- Outbound HTTPS to the License Authority (`ZLP_AUTHORITY_URL`)

---

## 2. Installation

Add the private Satis registry and your bearer token to `composer.json`, then require the package:

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
  },
  "require": {
    "zenplatform/zlf-php": "^1.0"
  }
}
```

```bash
composer install
```

The registry token is provided by the activation step below. On a fresh install, run activation first without the bearer token configured, then add it after.

---

## 3. Activation

Run the activation CLI once per server install. It generates a unique `install_id`, registers with the License Authority, and writes the initial token and shared secret to the local cache.

```bash
php vendor/bin/zlp-agent activate
```

The command prompts for three values (or reads them from environment variables if already set):

| Prompt | Env var override |
|--------|-----------------|
| License key (`ZLP-XXXX-XXXX-XXXX`) | `ZLP_LICENSE_KEY` |
| Product slug (e.g. `zenmsp`) | `ZLP_PRODUCT` |
| Install domain (e.g. `app.customer.com`) | `ZLP_DOMAIN` |

On success it prints:

```
Activation successful!

Set these environment variables on your server:
  ZLP_INSTALL_ID=<uuid>
  ZLP_LICENSE_KEY=ZLP-XXXX-XXXX-XXXX
  ZLP_PRODUCT=zenmsp
  ZLP_DOMAIN=app.customer.com
  ZLP_AUTHORITY_URL=https://license.yourdomain.com

Add to composer.json to pull SDK updates:
  "repositories": [{"type":"composer","url":"https://packages.yourdomain.com"}]
  "config": {"bearer": {"packages.yourdomain.com": "<registry_token>"}}

Add to crontab:
  */15 * * * * php vendor/bin/zlp-agent heartbeat >> /var/log/zlp-agent.log 2>&1
```

Set the printed environment variables on your server before starting the application. The `ZLP_INSTALL_ID` variable is required by the heartbeat agent.

---

## 4. Middleware Setup

Call `LicenseMiddleware::check()` at the top of every request, before any output or business logic. Any state other than `VALID` causes an immediate HTTP 402 response with `{"error":"license_required","state":"..."}`.

**Plain PHP (`index.php`):**

```php
<?php

require 'vendor/autoload.php';

use ZenPlatform\ZLF\LicenseMiddleware;

LicenseMiddleware::check('zenmsp');

// Your application starts here
```

**Laravel — register as global middleware (`bootstrap/app.php`):**

```php
use ZenPlatform\ZLF\LicenseMiddleware;
use Illuminate\Http\Request;

->withMiddleware(function (Middleware $middleware) {
    $middleware->prepend(function (Request $request, Closure $next) {
        LicenseMiddleware::check(config('zlp.product', 'zenmsp'));
        return $next($request);
    });
})
```

`check()` is idempotent within a single request — subsequent calls return the cached state from the first verification. The middleware never makes a network call; it reads the local cache and verifies the RS256 signature against the embedded public key.

---

## 5. Feature Gates

Feature gates must be enforced at the API/controller level. UI-only checks are not enforcement.

**Block a route or controller action:**

```php
use ZenPlatform\ZLF\LicenseMiddleware;

// Throws HTTP 402 if feature not present in the JWT
LicenseMiddleware::requireFeature('ms365');
```

`requireFeature()` calls `check()` internally — you do not need to call both.

**Conditional UI rendering (non-enforcing):**

```php
use ZenPlatform\ZLF\FeatureGate;

$token = LicenseMiddleware::getToken();
$tokenArray = $token ? (array) $token : [];

if (FeatureGate::hasFeature($tokenArray, 'multi_currency')) {
    // render currency selector
}
```

`hasFeature()` reads the decoded token in memory — it does not re-verify the JWT. Call it only after `check()` has already validated the token.

**Laravel example — feature middleware:**

```php
// In a route middleware:
public function handle(Request $request, Closure $next, string $feature): Response
{
    LicenseMiddleware::requireFeature($feature);
    return $next($request);
}

// On a route:
Route::get('/ms365', ...)->middleware('zlp.feature:ms365');
```

---

## 6. Heartbeat Agent

The heartbeat agent runs as a cron job. It POSTs a signed payload to the License Authority every 15 minutes and writes the refreshed JWT and rotated shared secret to the local cache.

**Add to crontab:**

```
*/15 * * * * php /path/to/vendor/bin/zlp-agent heartbeat >> /var/log/zlp-agent.log 2>&1
```

The `ZLP_INSTALL_ID`, `ZLP_LICENSE_KEY`, `ZLP_PRODUCT`, and `ZLP_DOMAIN` environment variables must be available to the cron user. Add them to `/etc/environment`, the cron user's `.bashrc`, or prefix the cron command:

```
*/15 * * * * ZLP_INSTALL_ID=<uuid> ZLP_LICENSE_KEY=... php vendor/bin/zlp-agent heartbeat >> /var/log/zlp-agent.log 2>&1
```

**What it does:**
1. Reads the current token and shared secret from the cache.
2. Builds a signed payload (`install_id`, `license_key`, `product`, `version`, `domain`, `fingerprint`, `timestamp`, `nonce`).
3. Signs with `HMAC-SHA256` using the shared secret and sends to `/v1/heartbeat`.
4. On `status: valid` — writes the new JWT and rotated shared secret to cache.
5. On `status: revoked` — writes a `BLOCKED` sentinel file immediately.
6. On network failure — retries with backoff (10 s, 30 s, 60 s). After three consecutive failures, writes `BLOCKED` and hard-blocks the install.

---

## 7. State Reference

| State | Trigger | HTTP response |
|-------|---------|---------------|
| `PENDING` | No cache file found; activation has not run | 402 `license_required` |
| `VALID` | Signature valid, `exp` in future, `install_id` and `product` match, `revoked` is false | Request proceeds |
| `EXPIRED` | Signature valid but `exp` has passed | 402 `license_required` |
| `INVALID` | Signature verification fails, claim mismatch, or JWT decode error | 402 `license_required` |
| `REVOKED` | JWT contains `"revoked": true`, or `BLOCKED` file exists | 402 `license_required` |

The middleware checks `exp` against the local clock on every request. No network call is made per-request.

---

## 8. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ZLP_INSTALL_ID` | Yes (after activation) | — | UUID assigned at activation; embedded in the JWT |
| `ZLP_LICENSE_KEY` | Yes (agent) | — | License key in `ZLP-XXXX-XXXX-XXXX` format |
| `ZLP_PRODUCT` | Yes (agent) | — | Product slug (e.g. `zenmsp`) |
| `ZLP_DOMAIN` | Yes (agent) | — | Canonical domain of this install |
| `ZLP_AUTHORITY_URL` | No | `https://license.yourdomain.com` | Base URL of the License Authority |
| `ZLP_CACHE_DIR` | No | `/var/lib/zlp` | Writable directory for token cache and BLOCKED file |

---

## 9. Hard Block Behavior

When the License Authority is unreachable, the agent retries three times with increasing backoff:

| Attempt | Wait before retry |
|---------|------------------|
| 1 | 10 seconds |
| 2 | 30 seconds |
| 3 | 60 seconds |
| After attempt 3 | Writes `BLOCKED` file — no further retries |

Once `BLOCKED` is written, every request returns HTTP 402 regardless of the cached JWT, even if the JWT has not yet expired. This matches the behavior of a revoked license.

To restore service after an unintended block: fix the network path to the License Authority, delete the `BLOCKED` file from `$ZLP_CACHE_DIR/{product}/BLOCKED`, and wait for the next successful heartbeat.

There is no grace period. An unreachable license server is treated identically to a revoked license.

---

## 10. Laravel-Specific Notes

**Global middleware registration** — Use `$middleware->prepend()` in `bootstrap/app.php` so the license check runs before route resolution, auth, and any other middleware.

**Scheduler instead of raw cron** — If you use Laravel Scheduler you can manage the heartbeat through `routes/console.php` instead of editing the system crontab:

```php
// routes/console.php (Laravel 11+)
use Illuminate\Support\Facades\Schedule;

Schedule::exec('php vendor/bin/zlp-agent heartbeat')
    ->everyFifteenMinutes()
    ->appendOutputTo(storage_path('logs/zlp-agent.log'));
```

You still need a single cron entry to drive the scheduler:

```
* * * * * cd /path/to/project && php artisan schedule:run >> /dev/null 2>&1
```

**Queued jobs** — Do not run the license check inside queued jobs. Queue workers are long-running processes that may outlive a valid token. The cron-based agent keeps the on-disk token fresh; the middleware check at the HTTP request boundary is sufficient.

**Cache driver** — The SDK does not use Laravel's cache system. It reads directly from the filesystem path set by `ZLP_CACHE_DIR`. Do not point `ZLP_CACHE_DIR` at `storage/app/public` or any path served by the web server.
