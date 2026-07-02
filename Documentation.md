# ZLP Integration Guide for AI Agents

**Audience:** Claude or any AI agent implementing ZLP licensing into a Zen product.  
**Read this entire file before touching any code in the target product.**

---

## What ZLP Does

ZLP is a cryptographic licensing system for self-hosted Zen products. Every HTTP request to a licensed product is gated by a locally cached RS256 JWT. A background agent (cron or `setInterval`) contacts the License Authority every 15 minutes to refresh that token. If the authority is unreachable after three retries, or if the license is revoked, the install writes a BLOCKED flag and all subsequent requests return HTTP 402. There is no grace period and no offline mode.

---

## How the System Works

```
Customer server                         License Authority (cloud)
──────────────────────────────────────────────────────────────────
[Cron / setInterval every 15 min]
  │
  ├─ Build payload: install_id, license_key,
  │  product, domain, fingerprint, nonce, timestamp
  ├─ Sign: HMAC-SHA256(payload, shared_secret)
  └─ POST /v1/heartbeat ─────────────────────────────────────────▶
                                                                  │
                         ◀─────────────── { status, token, shared_secret } ─┘

[Every HTTP request to the product]
  ├─ Read JWT from local cache file
  ├─ Verify RS256 signature (embedded public key — no network call)
  ├─ Check exp > now (local clock)
  ├─ Check install_id == locally stored install_id
  └─ Check product slug matches
       → VALID: continue
       → Any failure: HTTP 402, stop
```

The middleware never makes a network call. The agent does. These are two separate code paths.

---

## Before You Start

### 1. Ensure the product exists in ZLP Dashboard

Go to the ZLP Dashboard → **Products** and confirm the product slug exists (e.g. `zenmsp`). If not, create it there first.

### 2. Ensure plans are configured

Go to **Plans**, select the product. If no plans appear, click **Seed defaults** — this loads the pre-defined Starter / Professional / Enterprise tiers. You can also create plans manually. The features configured here are what end up in the JWT `features[]` claim.

### 3. Generate a license key

Go to **Keys** → **Generate Key**. Select the product, plan, and seat count. Copy the generated key (`ZLP-XXXX-XXXX-XXXX`). This is what the customer enters during activation.

---

## PHP Integration (e.g. ZenMSP)

### Step 1 — Add the SDK to composer.json

```json
{
  "repositories": [{
    "type": "composer",
    "url": "https://packages.yourdomain.com"
  }],
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

The `registry_token` is not available until after activation (Step 3). During initial setup, temporarily allow the package from a local path or run activation first to get the token.

### Step 2 — Set environment variables on the customer server

These must be present in the server environment (or `.env` loaded before the SDK is called):

| Variable | Description |
|---|---|
| `ZLP_INSTALL_ID` | UUID assigned at activation. Written by the activation CLI. |
| `ZLP_LICENSE_KEY` | The `ZLP-XXXX-XXXX-XXXX` key the customer purchased. |
| `ZLP_PRODUCT` | Product slug exactly as registered in ZLP Dashboard (e.g. `zenmsp`). |
| `ZLP_DOMAIN` | The domain this install runs on (e.g. `app.customer.com`). |
| `ZLP_AUTHORITY_URL` | `https://license.yourdomain.com` |
| `ZLP_CACHE_DIR` | Optional. Defaults to `/var/lib/zlp`. Must not be web-accessible. |

### Step 3 — Run activation (one-time per install)

```bash
ZLP_AUTHORITY_URL=https://license.yourdomain.com \
  php vendor/bin/zlp-agent activate
```

The CLI prompts for license key, product slug, and domain if the env vars are not set. On success it:
- Writes the JWT and shared secret to `/var/lib/zlp/{product}/token.cache` (mode 0600)
- Writes the install_id to `/var/lib/zlp/{product}/install.id` (mode 0600)
- Prints the env vars to set and the Composer registry bearer token

Set those env vars permanently before proceeding.

### Step 4 — Gate every request at the entry point

Add this as the **first executable line** of the product's bootstrap, before any output, routing, or session handling:

```php
use ZenPlatform\ZLF\LicenseMiddleware;

LicenseMiddleware::check('zenmsp');  // use your product slug
```

`check()` reads the cache, verifies the JWT locally, and either returns silently (state = VALID) or calls `http_response_code(402); exit(json_encode(['error' => 'license_required', 'state' => '...']));`.

**Do not wrap this in a try/catch at the entry point.** It must stop execution.

For an activation screen (PENDING state), read the state before calling check:

```php
use ZenPlatform\ZLF\LicenseMiddleware;
use ZenPlatform\ZLF\LicenseState;

$state = LicenseMiddleware::getState();
if ($state === LicenseState::PENDING) {
    // Show activation instructions, exit
}

LicenseMiddleware::check('zenmsp');
```

### Step 5 — Gate individual features

Call this immediately before any feature-specific logic, at the API route or controller level — not only in the UI:

```php
use ZenPlatform\ZLF\LicenseMiddleware;

// Before the MS365 integration
LicenseMiddleware::requireFeature('ms365');

// Before contracts module
LicenseMiddleware::requireFeature('contracts');

// Before multi-currency pricing
LicenseMiddleware::requireFeature('multi_currency');
```

`requireFeature()` reads the `features[]` array from the already-decoded in-memory token — zero I/O. Returns 402 with `{"error": "feature_not_licensed"}` if the feature is absent.

**Rule:** If a feature is gated in the UI (hidden nav item, disabled button), it must also be gated at the API route. UI-only gating is not enforcement.

### Step 6 — Set up the heartbeat cron

Add to the customer's crontab immediately after activation:

```
*/15 * * * * php /path/to/vendor/bin/zlp-agent heartbeat >> /var/log/zlp-agent.log 2>&1
```

The agent script reads `ZLP_INSTALL_ID`, `ZLP_LICENSE_KEY`, and `ZLP_PRODUCT` from the environment. These must be set in the cron environment (add them to `/etc/environment` or prefix the cron command).

---

## Node / Next.js Integration

### Step 1 — Add the SDK to package.json

Configure `.npmrc` in the project root:

```
@zenplatform:registry=https://npm.yourdomain.com
//npm.yourdomain.com/:_authToken=REGISTRY_TOKEN_FROM_ACTIVATION
```

```bash
npm install @zenplatform/zlf-node
```

### Step 2 — Set environment variables

| Variable | Description |
|---|---|
| `ZLP_INSTALL_ID` | UUID assigned at activation. |
| `ZLP_LICENSE_KEY` | The `ZLP-XXXX-XXXX-XXXX` key. |
| `ZLP_PRODUCT` | Product slug (e.g. `zenmsp`). |
| `ZLP_DOMAIN` | Install domain. |
| `ZLP_AUTHORITY_URL` | `https://license.yourdomain.com` |
| `DATA_DIR` | Optional. Defaults to `/var/lib/zlp`. Never set to a Next.js public path. |

### Step 3 — Run activation (one-time per install)

```bash
ZLP_AUTHORITY_URL=https://license.yourdomain.com \
  npx zlp activate
```

On success it writes the token cache to `$DATA_DIR/{product}/token.cache` and `install.id`, and prints the env vars to set.

### Step 4 — Add middleware (Next.js)

Create or update `middleware.ts` at the **project root** (not inside `src/` or `app/`):

```typescript
import { zlpMiddleware } from '@zenplatform/zlf-node';

export default zlpMiddleware({
  product: 'zenmsp',
  publicPaths: ['/login', '/activate', '/api/health', '/_next'],
});

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

`publicPaths` entries are matched with `startsWith`. Include every path that must be reachable before activation.

### Step 5 — Start the heartbeat agent

In `instrumentation.ts` (Next.js 14+ server instrumentation, runs once on server start):

```typescript
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { startLicenseAgent } = await import('@zenplatform/zlf-node');
    startLicenseAgent({
      product: 'zenmsp',
      intervalMs: 15 * 60 * 1000,
    });
  }
}
```

For non-Next.js Node apps, call `startLicenseAgent()` once at process startup.

### Step 6 — Gate features in API routes

**Route handler (pages router):**

```typescript
import { withFeature } from '@zenplatform/zlf-node';

export default withFeature('ms365')(async function handler(req, res) {
  // Only reached if ms365 is in the token features[]
  res.json({ data: '...' });
});
```

**Route handler (app router):**

```typescript
import { assertFeature } from '@zenplatform/zlf-node';

export async function GET() {
  assertFeature('ms365');  // throws → caught by error.tsx → 402
  return Response.json({ data: '...' });
}
```

**React Server Component:**

```typescript
import { assertFeature } from '@zenplatform/zlf-node';

export default function MS365Page() {
  assertFeature('ms365');  // throws if not licensed
  return <MS365Dashboard />;
}
```

---

## Feature Slugs

Feature slugs are configured per-product in the ZLP Dashboard → **Plans**. The slugs in the JWT `features[]` array must exactly match the strings passed to `requireFeature()` / `assertFeature()` / `withFeature()`. Check the dashboard for the current list before implementing gates.

Default slugs for `zenmsp`:

| Slug | Present in |
|---|---|
| `basic` | Starter, Professional, Enterprise |
| `ms365` | Professional, Enterprise |
| `contracts` | Professional, Enterprise |
| `multi_currency` | Professional, Enterprise |
| `quotes` | Enterprise |
| `custom_fields` | Enterprise |

If you add a new feature gate in the product code, add the corresponding slug to the relevant plans in the dashboard first, or existing Professional/Enterprise installs will be blocked from that feature at next heartbeat.

---

## State Machine Reference

Both SDKs implement identical states. The middleware reads this state on every request.

| State | Cause | Response |
|---|---|---|
| `PENDING` | No token file exists at `$cache_dir/{product}/token.cache` | Show activation screen |
| `VALID` | Signature good, `exp` in future, `install_id` matches, `product` matches, `revoked == false` | Allow request, check features |
| `EXPIRED` | JWT signature valid but `exp` is in the past | HTTP 402 |
| `INVALID` | Signature fails, wrong `install_id`, wrong `product`, wrong `iss` | HTTP 402 |
| `REVOKED` | `revoked == true` in JWT, or `BLOCKED` file exists in cache dir | HTTP 402 |

The `BLOCKED` file (`/var/lib/zlp/{product}/BLOCKED`) is written by the agent after 3 failed heartbeat retries or on a revoke response. Once written, no JWT verification is attempted — the middleware returns REVOKED immediately.

---

## JWT Payload Reference

The JWT issued by the License Authority contains:

```json
{
  "iss": "zlp.yourdomain.com",
  "sub": "install:<install_id>",
  "iat": 1718000000,
  "exp": 1718001800,
  "license_key": "ZLP-XXXX-XXXX-XXXX",
  "product": "zenmsp",
  "plan": "professional",
  "seats": 5,
  "features": ["basic", "ms365", "contracts", "multi_currency"],
  "domain": "app.customer.com",
  "install_id": "a3f9c821-...",
  "revoked": false
}
```

Access the decoded token in PHP: `LicenseMiddleware::getToken()` (returns `stdClass` or `null`).  
Access in Node: `getToken()` exported from `@zenplatform/zlf-node` (returns `DecodedToken` or `null`).

Use `plan` and `seats` for display purposes only. Use `features[]` for enforcement.

---

## File Paths Reference

| Path | Content | PHP | Node |
|---|---|---|---|
| `$ZLP_CACHE_DIR/{product}/token.cache` | JSON: `{token, shared_secret, cached_at}` | `/var/lib/zlp/` | `$DATA_DIR/` |
| `$ZLP_CACHE_DIR/{product}/install.id` | Plain UUID string | `/var/lib/zlp/` | `$DATA_DIR/` |
| `$ZLP_CACHE_DIR/{product}/BLOCKED` | Present = blocked | `/var/lib/zlp/` | `$DATA_DIR/` |

**None of these paths may be inside the web root, `public/`, `.next/`, or `storage/app/public/`.** The middleware will expose the JWT if any of these are web-accessible.

---

## Rules That Cannot Be Broken

1. **`server_unreachable` = hard block.** After 3 heartbeat failures the agent writes BLOCKED. The middleware then returns 402 identically to a revoked license. Do not add retry grace periods or cached-valid fallbacks.

2. **The middleware never makes a network call.** It reads the cache file and checks `exp` against the local clock. If you find yourself adding a fetch/curl inside the license check, you have misread the architecture.

3. **HTTP 402 for all license failures.** Not 403, not 500, not a redirect to `/login`. API routes return JSON. Non-API routes may redirect to `/license` or `/activate`.

4. **The public key is a constant in the SDK source.** It is never fetched at runtime. The key pair lives in `infra/keys/`. The public half is embedded in both `sdk-php/src/LicenseMiddleware.php` and `sdk-php/src/FeatureGate.php` (PHP) and in `sdk-node/src/jwtVerifier.ts` (Node).

5. **Feature gates must exist at the API level.** Hiding a UI element is cosmetic. The API route must also call `requireFeature()` / `withFeature()` / `assertFeature()`.

6. **`install_id` is validated in the JWT.** A token issued for install A returns INVALID on install B. Do not copy token cache files between servers.

---

## Troubleshooting

**"Activation failed: could not reach license authority"**  
→ Check `ZLP_AUTHORITY_URL`. The authority runs on port 7000 internally; externally it should be behind a reverse proxy on 443.

**State stays PENDING after activation**  
→ Confirm the cache file exists at `$ZLP_CACHE_DIR/{product}/token.cache` and is readable by the web server user. Confirm `ZLP_INSTALL_ID` matches the UUID in `install.id`.

**INVALID state immediately after activation**  
→ `install_id` in the JWT does not match `install.id` on disk, or the `product` slug in the JWT does not match what was passed to `check()`/`zlpMiddleware()`. Re-run activation.

**Features returning 402 for a plan that should include them**  
→ Check the plan config in ZLP Dashboard → Plans. The `features[]` in the JWT is snapshot at the time of the last heartbeat. If you added a feature to a plan in the dashboard, the install won't see it until the next successful heartbeat (up to 15 minutes).

**BLOCKED file written unexpectedly**  
→ The agent failed 3 heartbeat attempts in a row. Check `/var/log/zlp-agent.log`. Common causes: firewall blocking outbound to the authority, `ZLP_AUTHORITY_URL` wrong, or the authority service is down. Delete the BLOCKED file only after the underlying issue is resolved and a successful heartbeat has run.

**"feature_not_licensed" for a feature the plan should have**  
→ The feature slug in the code does not exactly match the slug in the dashboard plan config. Both are case-sensitive. Cross-check the feature slug in the dashboard against the string passed to `requireFeature()`.
