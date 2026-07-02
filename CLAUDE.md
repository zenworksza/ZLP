# ZLP — Zen License Platform
## Agent Build Instructions (`CLAUDE.md`)

> **Audience:** Claude (Opus), Kimi, Gemini  
> **Status:** Active build — follow this file as the single source of truth  
> **Version:** 1.0 | Internal · Confidential  
> **Last updated:** 2026-06-05

---

## 0. How to use this file

- **Read this entire file before touching any code.**
- All three agents share this file. Your assigned sections are marked `[CLAUDE]`, `[KIMI]`, or `[GEMINI]`. Untagged sections apply to everyone.
- When you complete a task, update the checklist item: `- [ ]` → `- [x]`.
- Never modify another agent's section without an explicit orchestration instruction from Claude.
- If you are unsure about a design decision, **stop and flag it** — do not invent a solution. The decision register is in Section 11.

---

## 1. Project Overview

**What this is:** Internal licensing infrastructure for all self-hosted Zen products (ZenMSP, ZenSSL, Imapsync GUI, and future products). Replaces the ad-hoc per-product ZLF implementation with a unified, cryptographically-hardened system.

**What this is NOT:** A multi-tenant SaaS platform. This is internal tooling — one vendor (us), many customer installs.

**Core guarantee:** A running install either has a valid signed token from our server, or it is hard-blocked. There is no fallback, no cached grace period, no offline mode.

---

## 2. Threat Model (read before writing any enforcement code)

Every enforcement decision must be made against this model.

| Threat | Vector | Closed by |
|---|---|---|
| Free riding | No key, expired key | Activation required — no token = no access |
| Network bypass | Firewall/DNS-redirect license server | Unreachable = hard block, same as invalid |
| Mock server | Local server returning `valid: true` | RS256 signature — cannot forge without private key |
| Replay attack | Captured valid JWT reused | `exp` TTL + `install_id` binding |
| Token extraction | Copy token to another host | Machine-bound cache + `install_id` in JWT |
| Middleware patch | Override `require_feature()` at runtime | Server-side API validation — UI gates are cosmetic |
| Session sharing | Multiple users on one login | Concurrent session ledger, seat limit server-side |
| API bypass | Direct curl to protected routes | License middleware on every route, not just UI |

**The Adobe CS rule:** `server_unreachable` and `license_invalid` trigger **identical hard blocks**. No exceptions. The historical crack worked by blocking the license server — if unreachable means valid, the whole system is broken.

---

## 3. Architecture

### 3.1 Component map

```
┌─────────────────────────────────────────────┐
│  CLOUD (our infrastructure)                  │
│                                             │
│  ┌─────────────────┐  ┌──────────────────┐ │
│  │ License Authority│  │  Vendor Dashboard│ │
│  │ FastAPI / Python │  │  React + FastAPI │ │
│  │ PostgreSQL 16    │  │  (vendor-only)   │ │
│  └────────┬─────────┘  └──────────────────┘ │
│           │                                  │
│  ┌────────┴────────────────────────────────┐ │
│  │  Private Package Registry               │ │
│  │  Satis (PHP)  +  Verdaccio (Node)       │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
              ▲ heartbeat POST (every 15 min)
              │ signed JWT response (TTL 30 min)
              ▼
┌─────────────────────────────────────────────┐
│  CUSTOMER SERVER                             │
│                                             │
│  ┌──────────────┐   ┌─────────────────────┐ │
│  │ Install Agent│   │  Product App        │ │
│  │ (daemon)     │──▶│  PHP / Next.js      │ │
│  │ writes token │   │  SDK Middleware      │ │
│  └──────────────┘   │  reads token cache  │ │
│                     └─────────────────────┘ │
└─────────────────────────────────────────────┘
```

### 3.2 Heartbeat loop (implement exactly as specified)

```
1.  Agent wakes (setInterval / cron, every 15 min)
2.  Build payload:
      { install_id, license_key, product, version,
        domain, fingerprint, timestamp, nonce }
3.  Sign payload:
      HMAC-SHA256(JSON.stringify(payload), shared_secret)
4.  POST /v1/heartbeat
      Headers: X-ZLF-Signature, X-ZLF-Timestamp
5.  License Authority checks:
      - Key exists and is not revoked
      - Payment current (no overdue > 24hr grace)
      - Fingerprint matches registered install
      → VALID:   return signed JWT + rotated shared_secret
      → INVALID: return { status: "revoked", reason: "..." }
      → TIMEOUT: agent retries 3× (10s → 30s → 60s backoff)
                 after 3rd failure → write BLOCKED state → hard block
6.  Agent writes token to machine-bound local cache
7.  Middleware reads cache on EVERY request
      - Verify RS256 signature against embedded public key
      - Check exp claim (local clock — no network call)
      - Check install_id matches local install_id
      → Any failure → HTTP 402
```

### 3.3 Middleware state machine

**Both PHP and Node SDKs must implement these five states identically.**

| State | Trigger | Response |
|---|---|---|
| `PENDING` | No token file exists | Show activation screen |
| `VALID` | Signature good, `exp` in future, `install_id` matches | Allow — check feature entitlements |
| `EXPIRED` | Signature good but `exp` passed | HTTP 402 |
| `INVALID` | Signature verification fails | HTTP 402 + alert vendor |
| `REVOKED` | Token contains `"revoked": true` or BLOCKED state written by agent | HTTP 402 + alert vendor |

**Rule:** HTTP 402 is the correct status for license issues. Do not use 403 (that implies authenticated but unauthorised). Do not redirect to login. Redirect to `/license` or return JSON `{ error: "license_required" }` for API routes.

---

## 4. JWT Design

The license token is the core artifact. Get this right.

### 4.1 Payload

```json
{
  "iss": "zlp.yourdomain.com",
  "sub": "install:<install_id>",
  "iat": 1718000000,
  "exp": 1718001800,
  "license_key": "ZLP-XXXX-XXXX-XXXX",
  "product": "zenmsp",
  "plan": "professional",
  "seats": 10,
  "features": ["ms365", "contracts", "multi_currency", "quotes"],
  "domain": "app.customer.com",
  "install_id": "a3f9c821-...",
  "revoked": false
}
```

### 4.2 Signing

- Algorithm: **RS256** (asymmetric — private key signs, public key verifies)
- Private key: stored on License Authority only, never distributed
- Public key: embedded as constant in both PHP and Node SDKs
- Key rotation: generate new keypair → distribute new SDK version → old keypair deprecated after 30-day overlap

### 4.3 Validation (middleware must check ALL of these)

```
1. Signature valid against embedded public key
2. exp > now (UTC)
3. iss == "zlp.yourdomain.com"
4. install_id == locally stored install_id
5. product == this product's slug
6. revoked == false
```

If any check fails → state = INVALID or EXPIRED as appropriate → HTTP 402.

### 4.4 Libraries (pinned)

| Language | Library | Version |
|---|---|---|
| Python (authority) | `python-jose[cryptography]` | `^3.3.0` |
| PHP (SDK) | `firebase/php-jwt` | `^6.0` |
| Node (SDK) | `jose` | `^5.0` |

---

## 5. Fingerprint Strategy

### 5.1 Composition

```
fingerprint = HMAC-SHA256(
  install_id + ":" + domain + ":" + machine_id,
  activation_secret
)
```

Where `activation_secret` is issued by the License Authority at activation and stored in machine-bound cache.

### 5.2 Machine ID by environment

| Environment | machine_id source |
|---|---|
| PHP / bare metal | `/etc/machine-id` → fallback: generate UUID, write to `/var/lib/zlp/machine.id` |
| Docker / Compose | UUID written to named volume at first run: `/data/zlp/machine.id` |
| Next.js / Node | UUID written to `$DATA_DIR/machine.id` at first run |
| Serverless / edge | `ZLP_INSTALL_ID` environment variable (set manually at deploy) |

### 5.3 Mismatch handling

| Scenario | Action |
|---|---|
| Domain matches, machine_id changed | Allow for 24hr + alert vendor (likely server migration) |
| Domain changed, machine_id matches | Alert + require re-activation within 24hr |
| Both changed | Immediate block — possible key sharing |

---

## 6. Database Schema

### 6.1 Tables [KIMI implements]

```sql
-- Products
CREATE TABLE products (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  slug        TEXT NOT NULL UNIQUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- License keys
CREATE TABLE license_keys (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    UUID NOT NULL REFERENCES products(id),
  key           TEXT NOT NULL UNIQUE,  -- format: ZLP-XXXX-XXXX-XXXX
  plan          TEXT NOT NULL,         -- starter | professional | enterprise
  seats         INT NOT NULL DEFAULT 1,
  expires_at    TIMESTAMPTZ,           -- NULL = no expiry (manual disable only)
  status        TEXT NOT NULL DEFAULT 'active',  -- active | suspended | revoked
  customer_ref  TEXT,                  -- free text — customer name / email
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Installs (one row per activated install)
CREATE TABLE installs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_id          UUID NOT NULL REFERENCES license_keys(id),
  install_id      TEXT NOT NULL UNIQUE,  -- UUID generated at activation
  domain          TEXT NOT NULL,
  fingerprint     TEXT NOT NULL,
  machine_id      TEXT NOT NULL,
  first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_heartbeat  TIMESTAMPTZ,
  status          TEXT NOT NULL DEFAULT 'active'  -- active | blocked | anomalous
);

-- Heartbeat log (append-only)
CREATE TABLE heartbeat_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  install_id      TEXT NOT NULL,  -- references installs.install_id
  timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
  latency_ms      INT,
  payload_hash    TEXT,           -- SHA256 of request payload
  response_status TEXT            -- valid | revoked | fingerprint_mismatch | error
);

-- Anomaly events
CREATE TABLE anomaly_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  install_id    TEXT NOT NULL,
  score         FLOAT NOT NULL,
  reason        TEXT NOT NULL,
  triggered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at   TIMESTAMPTZ
);

-- Audit trail
CREATE TABLE audit_trail (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor       TEXT NOT NULL,  -- 'system' or vendor user identifier
  action      TEXT NOT NULL,
  target_type TEXT,
  target_id   TEXT,
  timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta        JSONB
);
```

### 6.2 Indexes

```sql
CREATE INDEX idx_installs_key_id        ON installs(key_id);
CREATE INDEX idx_installs_install_id    ON installs(install_id);
CREATE INDEX idx_heartbeat_install_id   ON heartbeat_log(install_id);
CREATE INDEX idx_heartbeat_timestamp    ON heartbeat_log(timestamp DESC);
CREATE INDEX idx_license_keys_key       ON license_keys(key);
CREATE INDEX idx_license_keys_product   ON license_keys(product_id);
```

---

## 7. API Endpoints

### 7.1 License Authority endpoints [KIMI implements]

All endpoints require `Content-Type: application/json`. Heartbeat additionally requires `X-ZLF-Signature` and `X-ZLF-Timestamp` headers.

#### `POST /v1/activate`

**Request:**
```json
{
  "license_key": "ZLP-XXXX-XXXX-XXXX",
  "install_id": "uuid-v4",
  "domain": "app.customer.com",
  "fingerprint": "hmac-hex-string",
  "machine_id": "raw-machine-id",
  "product": "zenmsp",
  "version": "2.1.0"
}
```

**Response 200:**
```json
{
  "shared_secret": "base64-encoded-secret",
  "registry_token": "bearer-token-for-package-registry",
  "token": "<signed-JWT>"
}
```

**Errors:** `404` key not found | `409` key already activated on different domain | `402` key expired/revoked

---

#### `POST /v1/heartbeat`

**Headers:**
```
X-ZLF-Signature: hmac-sha256-hex
X-ZLF-Timestamp: unix-timestamp (reject if > 300s old)
```

**Request:**
```json
{
  "install_id": "uuid-v4",
  "license_key": "ZLP-XXXX-XXXX-XXXX",
  "product": "zenmsp",
  "version": "2.1.0",
  "domain": "app.customer.com",
  "fingerprint": "hmac-hex-string",
  "timestamp": 1718000000,
  "nonce": "random-hex-8"
}
```

**Response 200 (valid):**
```json
{
  "status": "valid",
  "token": "<signed-JWT>",
  "shared_secret": "<rotated-secret>"
}
```

**Response 200 (revoked/invalid):**
```json
{
  "status": "revoked",
  "reason": "license_suspended"
}
```

Note: Always return HTTP 200 for heartbeat responses. The SDK reads `status` field. HTTP errors (5xx) trigger the retry-then-block flow.

---

#### `POST /v1/revoke/{install_id}`

Vendor-only. Hard-blocks a specific install. Takes effect on next heartbeat (max 30 min).

**Response 200:**
```json
{ "revoked": true, "install_id": "uuid-v4" }
```

---

#### `GET /v1/status/{license_key}`

Vendor dashboard — returns all installs for a key with current status.

---

#### `GET /v1/health`

Public. Used by ALB health checks. Returns `{ "ok": true }`.

---

## 8. SDK Specifications

### 8.1 PHP SDK [KIMI implements]

**Package:** `zenplatform/zlf-php` via Satis registry  
**Min PHP:** 8.1  
**Dependencies:** `firebase/php-jwt ^6.0`, `guzzlehttp/guzzle ^7.0`

**File structure:**
```
src/
  LicenseMiddleware.php
  AgentDaemon.php         ← invoked by cron: * * * * * php vendor/bin/zlp-agent heartbeat
  Fingerprint.php
  TokenCache.php
  FeatureGate.php
  Activation.php
config/
  zlp_public.pem          ← RS256 public key, embedded
zlp-agent                 ← CLI entry point
```

**LicenseMiddleware.php — required interface:**
```php
// Call at top of every request before any output
LicenseMiddleware::check(string $productSlug): void;
// Throws LicenseException (→ HTTP 402) on any non-VALID state

// Feature gate — call before feature-specific logic
LicenseMiddleware::requireFeature(string $feature): void;
// Throws FeatureException (→ HTTP 402) if feature not in token

// Read current state without throwing
LicenseMiddleware::getState(): LicenseState; // enum: PENDING|VALID|EXPIRED|INVALID|REVOKED
```

**TokenCache.php — storage:**
- Path: `/var/lib/zlp/{product}/{install_id}.cache`
- Format: AES-256-GCM encrypted JSON, key derived from `machine_id + install_id`
- Never store in web root or any publicly accessible path

**AgentDaemon.php — cron entry:**
```bash
# Add to customer crontab at activation:
*/15 * * * * php /path/to/vendor/bin/zlp-agent heartbeat >> /var/log/zlp-agent.log 2>&1
```

**Note:** ionCube dropped — not required. Security is enforced cryptographically server-side (RS256 + HMAC). See OD-4.

---

### 8.2 Node / Next.js SDK [GEMINI implements]

**Package:** `@zenplatform/zlf-node` via Verdaccio registry  
**Min Node:** 18 LTS  
**Min Next.js:** 14 (App Router supported)  
**Dependencies:** `jose ^5.0` (only runtime dependency)

**File structure:**
```
src/
  middleware.ts     ← Next.js middleware.ts drop-in
  agent.ts          ← setInterval heartbeat daemon
  fingerprint.ts
  tokenCache.ts     ← module-level singleton
  featureGate.ts
  activation.ts     ← npx zlp activate
keys/
  zlp_public.pem
```

**middleware.ts — Next.js integration:**
```typescript
// In customer's middleware.ts at project root:
import { zlpMiddleware } from '@zenplatform/zlf-node';

export default zlpMiddleware({
  product: 'zenmsp',
  publicPaths: ['/login', '/activate', '/api/health'],
});

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

**agent.ts — daemon startup:**
```typescript
// Called once in server bootstrap (e.g. instrumentation.ts):
import { startLicenseAgent } from '@zenplatform/zlf-node';

startLicenseAgent({
  product: 'zenmsp',
  intervalMs: 15 * 60 * 1000,   // 15 min
});
```

**tokenCache.ts — singleton rules:**
- Token held in module-level variable (never written to a path accessible by HTTP)
- On Next.js: write to `process.env.DATA_DIR ?? '/var/lib/zlp'`
- Cache file encrypted: AES-256-GCM, key = `sha256(machine_id + install_id)`
- Singleton refreshed by agent; read by middleware — no locks needed (single-threaded Node)

**featureGate.ts:**
```typescript
// API route guard:
export function requireFeature(feature: string) {
  return (handler: NextApiHandler): NextApiHandler =>
    async (req, res) => {
      if (!hasFeature(feature)) return res.status(402).json({ error: 'feature_not_licensed' });
      return handler(req, res);
    };
}

// React Server Component check:
export function assertFeature(feature: string): void;  // throws → caught by error.tsx
```

---

## 9. Infrastructure

### 9.1 License Authority deployment [KIMI implements Docker Compose; Claude reviews AWS design]

```yaml
# docker-compose.yml (production)
services:
  license-authority:
    image: zenplatform/zlp-authority:latest
    restart: always
    environment:
      DATABASE_URL: postgres://...
      JWT_PRIVATE_KEY_PATH: /run/secrets/jwt_private.pem
      HMAC_ROTATION_SECRET: ${HMAC_ROTATION_SECRET}
    secrets:
      - jwt_private.pem

  postgres:
    image: postgres:16-alpine
    restart: always
    volumes:
      - pgdata:/var/lib/postgresql/data

  satis:
    image: zenplatform/zlp-satis:latest
    restart: always
    volumes:
      - satis-output:/var/www/satis

  verdaccio:
    image: verdaccio/verdaccio:5
    restart: always
    volumes:
      - verdaccio-storage:/verdaccio/storage
      - ./verdaccio.yaml:/verdaccio/conf/config.yaml
```

### 9.2 AWS requirements

| Resource | Spec |
|---|---|
| Primary region | eu-west-1 (existing) |
| Failover region | us-east-1 (active/passive) |
| Load balancer | ALB with `/v1/health` health check |
| Database | RDS PostgreSQL 16, Multi-AZ standby |
| Uptime target | 99.9% — maps to 15-min heartbeat interval |
| Status page | Required — customers must see vendor outages |

### 9.3 Private package registry

**PHP — Satis** at `packages.yourdomain.com`

Customer `composer.json`:
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
  }
}
```

**Node — Verdaccio** at `npm.yourdomain.com`

Customer `.npmrc`:
```
@zenplatform:registry=https://npm.yourdomain.com
//npm.yourdomain.com/:_authToken=REGISTRY_TOKEN_FROM_ACTIVATION
```

Registry tokens are issued at activation and stored in `license_keys.registry_token`. Revoking a license also invalidates the registry token — customers can no longer pull SDK updates.

---

## 10. Vendor Dashboard

[GEMINI implements frontend; KIMI implements backend API routes for dashboard]

### 10.1 Modules

| Module | Key features |
|---|---|
| Products | Create product, define tiers, configure feature flags per tier |
| Key management | Generate keys, assign plan + seats + expiry, view customer ref |
| Install registry | All activated installs per key — domain, fingerprint, first seen, last heartbeat, status |
| Heartbeat log | Per-install timeline — timestamp, latency, response status |
| Live status | VALID / EXPIRED / REVOKED / ANOMALOUS badges, auto-refresh every 60s |
| Remote disable | One-click block on install or entire key |
| Anomaly alerts | Fingerprint drift, geo spread, session spikes — dashboard + email |
| Audit log | All vendor actions with timestamp |

### 10.2 Anomaly scoring

Alert threshold: score > 0.6  
Auto-block threshold: score > 0.85

```python
def anomaly_score(install_id: str, window_hours: int = 24) -> float:
    events = get_recent_heartbeats(install_id, window_hours)
    
    unique_ips    = len(set(e.source_ip for e in events))
    unique_geos   = len(set(e.geo_country for e in events))
    ua_changes    = count_ua_switches(events)
    fp_mismatches = sum(1 for e in events if e.response_status == 'fingerprint_mismatch')
    
    score = (
        min(unique_ips / 5, 1.0)    * 0.30 +
        min(unique_geos / 3, 1.0)   * 0.30 +
        min(ua_changes / 3, 1.0)    * 0.20 +
        min(fp_mismatches / 2, 1.0) * 0.20
    )
    return round(score, 4)
```

### 10.3 Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11+) |
| Frontend | React 18 + Vite + TailwindCSS |
| Database | PostgreSQL 16 (shared with License Authority) |
| Auth | JWT sessions — vendor-only, no customer logins |
| Jobs | APScheduler — heartbeat expiry checker every 5 min, alert dispatcher |
| Email | SMTP (configurable) |

---

## 11. Open Decisions (do not implement until resolved — flag to Claude)

| ID | Decision | Options |
|---|---|---|
| OD-1 | Heartbeat interval | 15 min recommended — confirm before daemon implementation |
| OD-2 | Token TTL | 30 min recommended — must exceed daemon interval |
| OD-3 | Anomaly auto-block threshold | 0.85 proposed — tune after first month of data |
| OD-4 | ~~ionCube scope~~ | **Closed** — ionCube dropped. Security is enforced cryptographically (RS256 + HMAC); obfuscation adds no meaningful protection. |
| OD-5 | Serverless tier policy | First-class support or best-effort/documented-limitation? |
| OD-6 | Billing gateway | Which gateway triggers license status update? |
| OD-7 | Registry token lifetime | Tied to license validity, or annual rotation? |
| OD-8 | Multi-region strategy | Active/passive (simpler) or active/active? |

---

## 12. Agent Task Checklists

### 12.1 Claude — Architect & Orchestrator

- [ ] Finalise OpenAPI spec for all License Authority endpoints (`/docs/openapi.yaml`)
- [ ] Generate RS256 keypair and define key storage/rotation procedure
- [ ] Define activation_secret derivation and rotation protocol
- [ ] Review Kimi's `/v1/heartbeat` implementation against Section 3.2
- [ ] Review Kimi's JWT issuance against Section 4
- [ ] Review Gemini's Node middleware state machine against Section 3.3
- [ ] Verify PHP SDK and Node SDK implement identical state machine behaviour
- [ ] Security review of TokenCache encryption in both SDKs
- [ ] Sign off on Phase 1 before Phase 2 begins
- [ ] Sign off on Phase 2 before Phase 3 begins
- [ ] Resolve open decisions OD-1 through OD-8 (coordinate with Kimi/Gemini)
- [ ] Final security audit before production deployment
- [ ] Write ZenMSP migration plan (ZLF → ZLP)
- [ ] Keep this CLAUDE.md updated as decisions are made

### 12.2 Kimi — Implementation Lead (PHP + Python + Infrastructure)

- [x] PostgreSQL schema — all tables and indexes from Section 6
- [x] Alembic migration: `001_initial_schema.py`
- [x] Alembic migration: `002_phase2_fixes.py` — encrypted secret storage
- [x] FastAPI app skeleton with health endpoint
- [x] `POST /v1/activate` endpoint (with secret encryption)
- [x] `POST /v1/heartbeat` endpoint (HMAC validation + JWT issuance + secret rotation)
- [x] `POST /v1/revoke/{install_id}` endpoint
- [x] `GET /v1/status/{license_key}` endpoint
- [x] Encryption utilities (`crypto.py`) — AES-256-GCM secret storage
- [x] PHP SDK: `TokenCache.php` — JSON storage with token + secret
- [x] PHP SDK: `LicenseMiddleware.php` — five-state machine + HTTP 402 responses
- [x] PHP SDK: `AgentDaemon.php` — heartbeat POST with retry/backoff, cache-based secrets
- [ ] Dashboard backend API routes (install registry, heartbeat log, anomaly events)
- [ ] APScheduler jobs: heartbeat expiry checker, anomaly scorer, alert dispatcher
- [ ] PHP SDK: `Fingerprint.php` — `/etc/machine-id` reader with volume fallback
- [ ] PHP SDK: `FeatureGate.php` — `requireFeature()` against JWT features array
- [ ] PHP SDK: `Activation.php` — CLI activation flow
- [ ] PHP SDK: Composer package structure and Satis registry config
- [x] ~~ionCube encoding pipeline~~ — dropped (OD-4 closed)
- [ ] Unit tests: all five middleware states (PHP)
- [ ] Docker Compose: License Authority + PostgreSQL + Satis + Verdaccio
- [ ] Verdaccio `config.yaml` with scoped `@zenplatform` packages and bearer auth

### 12.3 Gemini — Large-Context Analysis + Node SDK + Dashboard UI

- [x] Node SDK: `tokenCache.ts` — JSON storage with token + secret, backwards compatible
- [x] Node SDK: `middleware.ts` — Next.js middleware drop-in, five-state machine
- [x] Node SDK: `agent.ts` — setInterval heartbeat with retry/backoff, cache-based secrets
- [ ] Node SDK: `fingerprint.ts` — domain + volume UUID composite
- [ ] Node SDK: `featureGate.ts` — `requireFeature()` HOC + API route guard
- [ ] Node SDK: `activation.ts` — `npx zlp activate` CLI flow
- [ ] Node SDK: npm package structure and Verdaccio publish config
- [x] Parity audit: Node SDK uses same secret management as PHP SDK
- [x] Parity audit: heartbeat HMAC signing identical across both SDKs
- [ ] React dashboard: Products module
- [ ] React dashboard: Key management module
- [ ] React dashboard: Install registry with live status badges
- [ ] React dashboard: Heartbeat log timeline per install
- [ ] React dashboard: Remote disable controls
- [ ] React dashboard: Anomaly alerts panel
- [ ] React dashboard: Audit log
- [ ] Integration test suite: activation → heartbeat → revocation end-to-end
- [ ] Integration test suite: fingerprint mismatch scenarios
- [ ] Integration test suite: retry/backoff → hard block flow
- [ ] SDK documentation: PHP integration guide (`docs/sdk-php.md`)
- [ ] SDK documentation: Node/Next.js integration guide (`docs/sdk-node.md`)

---

## 13. Build Phases

### Phase 1 — Foundation (Weeks 1–2)
**Goal:** License Authority accepts activations and issues valid JWTs. Both SDK skeletons exist.

- Claude: OpenAPI spec, keypair generation, CLAUDE.md seed ✓
- Kimi: Schema + migrations, FastAPI skeleton, `/v1/activate`, `/v1/health`
- Gemini: Node SDK skeleton, `middleware.ts` state machine stub with mock token

**Phase 1 exit criteria (Claude signs off):**
- `/v1/activate` returns a verifiable RS256 JWT
- PHP middleware correctly enters VALID state from that JWT
- Node middleware correctly enters VALID state from that JWT

### Phase 2 — Core Enforcement (Weeks 3–4)
**Goal:** Full heartbeat loop working. Hard block on all failure cases.

- Kimi: `/v1/heartbeat`, PHP agent daemon, all five PHP states, retry/backoff
- Gemini: Node agent, full Node state machine, `featureGate.ts`
- Claude: Review crypto implementation, state machine parity check

**Phase 2 exit criteria (Claude signs off):**
- Firewall test: block license server → install hard-blocks within 30 min
- Revocation test: revoke via API → install hard-blocks within 30 min
- Stolen token test: copy JWT to different machine → INVALID state

### Phase 3 — Dashboard & Registry (Weeks 5–6)
**Goal:** Vendor can manage keys, view installs, and remotely disable.

- Gemini: React dashboard (all modules)
- Kimi: Remote disable endpoint, anomaly jobs, Satis + Verdaccio configured
- Claude: End-to-end review, threat model re-check

### Phase 4 — Hardening & Migration (Weeks 7–8)
**Goal:** Production-ready. ZenMSP migrated from ZLF to ZLP.

- Kimi: production Docker Compose (ionCube dropped — OD-4 closed)
- Gemini: Integration test suite, SDK docs
- Claude: Final security audit, ZenMSP migration plan + execution

---

## 14. File Conventions

```
/
  CLAUDE.md                  ← this file — update as you go
  docs/
    openapi.yaml             ← Claude owns
    sdk-php.md               ← Gemini owns
    sdk-node.md              ← Gemini owns
  authority/                 ← FastAPI License Authority (Kimi)
    app/
      main.py
      routers/
        activate.py
        heartbeat.py
        revoke.py
        status.py
      models/
      schemas/
      services/
        jwt_service.py
        fingerprint_service.py
        anomaly_service.py
    alembic/
    tests/
  dashboard/                 ← React frontend (Gemini) + FastAPI routes (Kimi)
    frontend/
    backend/
  sdk-php/                   ← PHP SDK (Kimi)
  sdk-node/                  ← Node SDK (Gemini)
  infra/
    docker-compose.yml
    verdaccio.yaml
    satis/
```

---

## 15. Non-Negotiable Rules

These cannot be overridden by any agent for any reason.

1. **`server_unreachable` = hard block.** No cached fallback. No grace period. If the retry sequence exhausts (3 attempts), write BLOCKED state and block.
2. **JWT expiry is checked locally on every request.** The middleware never makes a network call per-request. It reads the cache and checks `exp` against local clock.
3. **HTTP 402 for all license failures.** Not 403. Not 500. Not a redirect to login.
4. **`install_id` is validated in the JWT.** A token issued for install A must fail verification on install B.
5. **No feature gate lives only in the UI.** Every protected feature must be gated at the API route level. UI hiding is optional UX, not enforcement.
6. **Public key is embedded, not fetched.** The SDK never fetches the public key at runtime. It is a constant in the source. Fetching it at runtime opens a MITM vector.
7. **Shared secret rotates on every successful heartbeat.** A captured heartbeat request cannot be replayed — the HMAC key will have changed.
8. **Token cache is never in the web root.** PHP: `/var/lib/zlp/`. Node: `$DATA_DIR`. Never `public/`, never `.next/`, never `storage/app/public/`.
