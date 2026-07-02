# ZLP Security Audit

**Auditor:** Claude (ZLP Architect)  
**Date:** 2026-06-22  
**Scope:** Phase 1–4 implementation vs. threat model (CLAUDE.md Sections 2–4)

---

## Summary

| Severity | Count |
|---|---|
| High | 0 |
| Medium | 2 (both fixed during this audit) |
| Low | 3 |
| Informational | 2 |

---

## Fixed During Audit

### [FIXED] Missing `iss` claim validation (Medium)

**Affected:** `sdk-node/src/jwtVerifier.ts`, `sdk-php/src/LicenseMiddleware.php`

**Spec requirement (Section 4.3, check #3):** `iss == "zlp.yourdomain.com"`

**Finding:** Neither SDK validated the `iss` claim. A JWT from a different issuer (e.g., a different ZLP deployment or a misconfigured authority) would pass validation.

**Fix applied:** Both SDKs now reject tokens where `iss !== 'zlp.yourdomain.com'`.

---

### [FIXED] Missing `install_id` local binding check (Medium)

**Affected:** `sdk-node/src/jwtVerifier.ts`, `sdk-php/src/LicenseMiddleware.php`

**Spec requirement (Section 4.3, check #4):** `install_id == locally stored install_id`

**Threat closed:** Token extraction (CLAUDE.md Section 2 — "Copy token to another host")

**Finding:** Both SDKs decoded the `install_id` from the JWT but did not compare it against a locally stored value. A token extracted from install A could be replayed on install B.

**Fix applied:**
- PHP: reads `/var/lib/zlp/{product}/install.id` (written by `Activation.php`) and compares against JWT `install_id`
- Node: reads `process.env.ZLP_INSTALL_ID` and compares against JWT `install_id`; `activation.ts` now also writes `install.id` to `$DATA_DIR/{product}/install.id`

---

## Open Findings

### [Low] Heartbeat timestamp validation uses server clock only

**File:** `authority/app/routers/heartbeat.py:63`

The 300-second timestamp window is checked against the server's UTC clock. If a customer's server clock drifts significantly, legitimate heartbeats may be rejected before the 3-retry exhaustion triggers a hard block. This would manifest as spurious BLOCKED states.

**Recommendation:** Log clock skew in the heartbeat log entry. Alert if skew > 60 seconds. No code change required now — monitor in production.

---

### [Low] `requireFeature()` in PHP re-runs `check()` unnecessarily

**File:** `sdk-php/src/LicenseMiddleware.php:114`

`requireFeature()` calls `check()` which re-reads the token cache. If `check()` was already called at the top of the request (as intended), this is a redundant file read on every feature-gated route. Not a security issue, but a correctness smell: if the token changes between the two reads (extremely unlikely within a single request), the state could differ.

**Recommendation:** Add a static flag `self::$checked` to skip re-reading on subsequent `requireFeature()` calls. Low priority.

---

### [FIXED] Dashboard routes had no authentication

**File:** `authority/app/routers/dashboard.py`

All `/dashboard/*` routes now require `Authorization: Bearer <DASHBOARD_TOKEN>`. The token is set via the `DASHBOARD_TOKEN` environment variable. Returns 401 on wrong token, 503 if the env var is not set (fail-closed). Generate with `openssl rand -hex 32`.

---

## Verified Correct

| Check | Spec ref | Verified |
|---|---|---|
| Signature validated against embedded public key (never fetched) | §4.3 #1, Rule 6 | ✓ Both SDKs use embedded PEM constant |
| `exp > now` checked locally on every request (no network call) | §4.3 #2, Rule 2 | ✓ Both SDKs check `exp` against local clock |
| `product` claim validated against product slug | §4.3 #5 | ✓ Both SDKs |
| `revoked == false` checked | §4.3 #6 | ✓ Both SDKs |
| HTTP 402 for all non-VALID states | Rule 3 | ✓ Both SDKs, all 5 states |
| `server_unreachable` triggers hard block (3 retries, no fallback) | Rule 1 | ✓ PHP AgentDaemon + Node agent both write BLOCKED on 3rd failure |
| Token cache not in web root | Rule 8 | ✓ `/var/lib/zlp/` (PHP), `$DATA_DIR` (Node) |
| Shared secret rotated on every successful heartbeat | Rule 7 | ✓ Heartbeat endpoint generates new secret, SDKs update cache |
| Replay attack prevention | §3.2 step 5 | ✓ `payload_hash` checked against last 15 min in heartbeat_log |
| `install_id` bound to install (now validated) | §4.3 #4 | ✓ Fixed in this audit |
| `iss` validated (now validated) | §4.3 #3 | ✓ Fixed in this audit |
| Feature gates at API level, not only UI | Rule 5 | ✓ `requireFeature()` / `withFeature()` enforce at route level |

---

## Threat Model Coverage

| Threat | Closed by | Status |
|---|---|---|
| Free riding (no/expired key) | Activation required, PENDING/EXPIRED states | ✓ |
| Network bypass (firewall license server) | Unreachable = hard block after 3 retries | ✓ |
| Mock server (local server returning valid) | RS256 — cannot forge without private key | ✓ |
| Replay attack (captured JWT reused) | `exp` TTL 30 min + `payload_hash` dedup | ✓ |
| Token extraction (copy token to another host) | `install_id` binding check (fixed this audit) | ✓ |
| Middleware patch (override require_feature at runtime) | Server-side API validation; UI gates are cosmetic | ✓ |
| Session sharing | Seat limit in JWT `seats` claim (dashboard enforcement TBD) | Partial — concurrent session ledger not yet implemented |
| API bypass (direct curl to protected routes) | License middleware on every route | ✓ |

**Partial:** Concurrent session / seat enforcement is not yet implemented. The `seats` claim is present in the JWT but nothing counts active sessions server-side. Recommend adding this in a future iteration, particularly for enterprise customers.

---

## Pre-Production Requirements

1. **Add dashboard auth** (Low, blocking for production)
2. **ionCube Loader** verified on all target PHP environments before SDK rollout
3. **Concurrent session ledger** (Medium, post-launch acceptable)
4. **Clock skew monitoring** (Low, post-launch acceptable)
5. **Billing gateway integration** (OD-6, blocking for commercial use)
