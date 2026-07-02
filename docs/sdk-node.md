# ZLP Node / Next.js SDK Integration Guide

Package: `@zenplatform/zlf-node`

---

## 1. Requirements

- Node.js 18 LTS or later
- Next.js 14 or later (App Router and Pages Router both supported)
- A writable directory for the token cache — default `/var/lib/zlp/`, override with `DATA_DIR`
- Outbound HTTPS to the License Authority (`ZLP_AUTHORITY_URL`)
- A long-running server process (not compatible with serverless or edge runtimes — see Section 11)

---

## 2. Installation

Add the private Verdaccio registry to your project's `.npmrc`, then install the package:

```ini
# .npmrc
@zenplatform:registry=https://npm.yourdomain.com
//npm.yourdomain.com/:_authToken=REGISTRY_TOKEN_FROM_ACTIVATION
```

```bash
npm install @zenplatform/zlf-node
```

The registry token is provided by the activation step below. On a fresh install, run activation first to obtain the token.

---

## 3. Activation

Run the activation CLI once per server install. It generates a unique `install_id`, registers with the License Authority, and writes the initial token and shared secret to the local cache.

```bash
npx zlp activate
```

The command prompts for three values (or reads them from environment variables if already set):

| Prompt | Env var override |
|--------|-----------------|
| License key (`ZLP-XXXX-XXXX-XXXX`) | `ZLP_LICENSE_KEY` |
| Product slug (e.g. `zenmsp`) | `ZLP_PRODUCT` |
| Install domain (e.g. `app.customer.com`) | `ZLP_DOMAIN` |

On success it prints:

```
[ZLP] Activation successful.
[ZLP] install_id: <uuid>

[ZLP] Add the following to your .npmrc to access the package registry:
//npm.yourdomain.com/:_authToken=<registry_token>
@zenplatform:registry=https://npm.yourdomain.com

[ZLP] Set these environment variables on your server:
ZLP_INSTALL_ID=<uuid>
ZLP_LICENSE_KEY=ZLP-XXXX-XXXX-XXXX
ZLP_PRODUCT=zenmsp
ZLP_DOMAIN=app.customer.com
```

Add these to `.env.local` (local development) or your server's environment (production). The `ZLP_INSTALL_ID` variable is required by the heartbeat agent.

```ini
# .env.local
ZLP_INSTALL_ID=<uuid from activation>
ZLP_LICENSE_KEY=ZLP-XXXX-XXXX-XXXX
ZLP_PRODUCT=zenmsp
ZLP_DOMAIN=app.customer.com
ZLP_AUTHORITY_URL=https://license.yourdomain.com
DATA_DIR=/var/lib/zlp
```

---

## 4. Next.js Middleware

Create or update `middleware.ts` at your project root. The SDK exports a factory function that returns a Next.js-compatible middleware handler.

```typescript
// middleware.ts (project root)
import { zlpMiddleware } from '@zenplatform/zlf-node/middleware';

export default zlpMiddleware({
  product: 'zenmsp',
  publicPaths: ['/login', '/activate', '/api/health'],
});

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

**`ZLPConfig` options:**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `product` | `string` | Yes | Product slug — must match the slug in the JWT |
| `publicPaths` | `string[]` | No | Path prefixes that bypass license checks |

The middleware reads the local token cache and verifies the RS256 signature on every request. No network call is made per-request. Any state other than `VALID` returns HTTP 402:

```json
{ "error": "license_required", "state": "EXPIRED" }
```

---

## 5. Heartbeat Agent

The heartbeat agent runs on the server and keeps the cached token fresh. Add it to `instrumentation.ts` (Next.js instrumentation hook) so it starts with the server process.

```typescript
// instrumentation.ts (project root)
export async function register() {
  // Guard: only run on the server, not in the edge runtime
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { startLicenseAgent } = await import('@zenplatform/zlf-node');
    startLicenseAgent({
      product: 'zenmsp',
      // intervalMs defaults to 15 minutes (900000)
    });
  }
}
```

Enable the instrumentation hook in `next.config.js` if not already enabled:

```javascript
// next.config.js
module.exports = {
  experimental: {
    instrumentationHook: true,
  },
};
```

**What the agent does:**
1. Runs a heartbeat immediately on startup, then every 15 minutes.
2. Reads the current token and shared secret from the cache.
3. Builds a signed payload and POSTs to `/v1/heartbeat` with `X-ZLF-Signature` and `X-ZLF-Timestamp` headers.
4. On `status: valid` — writes the new JWT and rotated shared secret to cache.
5. On `status: revoked` — writes a `BLOCKED` sentinel file immediately.
6. On network failure — retries with backoff (10 s, 30 s, 60 s). After three failures, writes `BLOCKED` and hard-blocks the install.

`startLicenseAgent` uses `setInterval` and requires a persistent Node.js process. Do not call it in edge functions, middleware, or API routes.

---

## 6. Feature Gates

Feature gates must be enforced at the API route level. Client-side or RSC-only checks are not enforcement.

**Check a feature without throwing (conditional rendering):**

```typescript
import { requireFeature } from '@zenplatform/zlf-node';
import { getToken } from '@zenplatform/zlf-node/middleware';

const token = getToken();
if (requireFeature('ms365', token)) {
  // render ms365 UI
}
```

**Pages Router — API route guard (`withFeature` HOC):**

```typescript
// pages/api/ms365/sync.ts
import type { NextApiRequest, NextApiResponse } from 'next';
import { withFeature } from '@zenplatform/zlf-node';

// Attach the decoded token to the request before calling the HOC.
// This is typically done in a shared wrapper that calls getToken() from middleware.
function handler(req: NextApiRequest, res: NextApiResponse) {
  res.json({ ok: true });
}

export default withFeature('ms365')(handler);
```

`withFeature` reads `req.__zlpToken`. You must attach the decoded token to `req` before the HOC runs — typically in a shared request wrapper that calls `getToken()` from the middleware module and sets `(req as any).__zlpToken = token`.

**App Router / React Server Components (`assertFeature`):**

```typescript
// app/ms365/page.tsx
import { assertFeature } from '@zenplatform/zlf-node';
import { getToken } from '@zenplatform/zlf-node/middleware';

export default function MS365Page() {
  // Throws 'feature_not_licensed' — caught by the nearest error.tsx boundary
  assertFeature('ms365', getToken());

  return <div>MS365 content</div>;
}
```

**Summary of gate functions:**

| Function | Returns | Throws | Use case |
|----------|---------|--------|----------|
| `requireFeature(feature, token)` | `boolean` | No | Conditional rendering / branching |
| `withFeature(feature)(handler)` | `NextApiHandler` | No (returns 402) | Pages Router API routes |
| `assertFeature(feature, token)` | `void` | Yes (`Error`) | RSC — caught by `error.tsx` |

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
| `DATA_DIR` | No | `/var/lib/zlp` | Writable directory for token cache and BLOCKED file |

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

To restore service after an unintended block: fix the network path to the License Authority, delete the `BLOCKED` file from `$DATA_DIR/{product}/BLOCKED`, and restart the server so the agent runs a new heartbeat immediately on startup.

There is no grace period. An unreachable license server is treated identically to a revoked license.

---

## 10. Token Cache Location

The cache file is stored at:

```
$DATA_DIR/{product}/token.cache
```

Default with `DATA_DIR=/var/lib/zlp` and `product=zenmsp`:

```
/var/lib/zlp/zenmsp/token.cache
```

The file is written with mode `0600` (owner read/write only). The `BLOCKED` sentinel file is written to the same directory: `/var/lib/zlp/zenmsp/BLOCKED`.

**The cache must never be placed in a web-accessible path.** Specifically:

- Do not set `DATA_DIR` to anything under `.next/`
- Do not set `DATA_DIR` to anything under `public/`
- Do not symlink the cache directory into the web root

If the `DATA_DIR` is not writable, activation will fail and the agent will not be able to refresh the token.

---

## 11. Serverless / Edge Runtime

The heartbeat agent uses `setInterval` and requires a persistent Node.js process. It is **not compatible** with:

- Vercel Serverless Functions
- Next.js Edge Runtime (middleware running on the edge)
- AWS Lambda or similar function-as-a-service platforms

**If you must deploy to a serverless environment:**

1. Set `ZLP_INSTALL_ID` as an environment variable at deploy time (do not rely on runtime generation).
2. Run the heartbeat agent in a separate persistent process — for example, a small Node.js daemon on a VM, or an ECS task — that has access to the same `DATA_DIR` mount.
3. Share the `DATA_DIR` between the persistent agent process and the serverless function instances (e.g. via EFS or a similar network filesystem).
4. The middleware can read the token from the shared filesystem on each request. Signature verification works without a running agent — but without an agent writing fresh tokens, the install will hard-block when the current JWT expires (30 minutes from the last successful heartbeat).

Serverless support is a best-effort configuration. For production use, a long-running Node.js server (Next.js custom server, or a standalone Node process) is recommended.
