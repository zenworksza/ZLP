# ZLP — Final Audit & Completion Plan
**Date:** 2026-07-02  
**Based on:** Full codebase audit against CLAUDE.md, Snaglist.md, and phase completion reports

---

## Executive Summary

Phases 1–3 are architecturally complete and the threat model is correctly implemented.  
Four bugs need fixing before the test suite can pass. One architectural decision has been made (drop ionCube).  
One infrastructure gap (Satis) needs closing. After that, only Phase 4 migration work remains.

---

## Section 1 — Bugs to Fix

These must be resolved before the test suite can be used as a CI gate.

---

### Bug 1 — `machine_id` missing from integration test heartbeat payload
**File:** `tests/test_integration.py:58–68`  
**Severity:** Blocks all 4 heartbeat tests

`HeartbeatRequest` (Pydantic model) declares `machine_id: str` as required.  
`_heartbeat_payload()` does not include it. Every heartbeat test returns HTTP 422 instead of 200.

**Fix:** Add `"machine_id": "test-machine-id"` to `_heartbeat_payload()`.

```python
def _heartbeat_payload(install_id: str, domain: str = "app.customer.com") -> dict:
    return {
        "install_id": install_id,
        "license_key": "ZLP-TEST-1234-ABCD",
        "product": "zenmsp",
        "version": "2.1.0",
        "domain": domain,
        "fingerprint": "deadbeef" * 8,
        "machine_id": "test-machine-id",   # ADD THIS
        "timestamp": int(time.time()),
        "nonce": secrets.token_hex(8),
    }
```

**Tests affected:** `test_heartbeat_valid`, `test_heartbeat_invalid_signature`, `test_heartbeat_replay`, `test_heartbeat_after_revoke`

---

### Bug 2 — Dashboard test sends no auth header
**File:** `tests/test_integration.py:283`  
**Severity:** Blocks `test_dashboard_stats`

The dashboard router requires `Authorization: Bearer <token>`. The test client sends none.  
`HTTPBearer` rejects with HTTP 403 before reaching the route. Test asserts 200.

**Fix:** Set `DASHBOARD_TOKEN` in the test environment and pass the header.

In `tests/conftest.py`, patch the env var in the `client` fixture:
```python
with patch.dict(os.environ, {"DASHBOARD_TOKEN": "test-token"}), \
     patch.object(app_module, "start_scheduler", lambda: None), \
     ...
```

In `test_integration.py`, update the dashboard test to include the header:
```python
async def test_dashboard_stats(client: AsyncClient, seed_db):
    r = await client.get(
        "/dashboard/stats",
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
```

---

### Bug 3 — PHP unit test: expired token asserts INVALID, code returns EXPIRED
**File:** `sdk-php/tests/LicenseMiddlewareTest.php:186`  
**Severity:** Fails `test_expired_state_with_expired_token`

`LicenseMiddleware.php` explicitly catches `\Firebase\JWT\ExpiredException` and returns `LicenseState::EXPIRED`.  
The test asserts `LicenseState::INVALID`. The comment in the test is incorrect.

**Fix:** Correct the assertion (the code is right, the test is wrong):
```php
$this->assertSame(LicenseState::EXPIRED, $state);
```

And update or remove the misleading comment above it.

---

### Bug 4 — License key generation uses non-cryptographic PRNG
**File:** `authority/app/routers/dashboard.py:97`  
**Severity:** Security issue — license keys are predictable

```python
# WRONG — random.choices is a PRNG, not cryptographically secure
segments = ["".join(random.choices(chars, k=6)) for _ in range(4)]
```

**Fix:** Use `secrets` module:
```python
import secrets

def _generate_license_key() -> str:
    chars = string.ascii_uppercase + string.digits
    segments = ["".join(secrets.choice(chars) for _ in range(6)) for _ in range(4)]
    return "ZLP-" + "-".join(segments)
```

Also remove `import random` from the top of `dashboard.py` if it is no longer used elsewhere in that file.

---

## Section 2 — Architectural Decision: Drop ionCube

**Decision:** ionCube is removed from scope. OD-4 is closed.

**Rationale:**  
ZLP's security guarantees are cryptographic, not obfuscation-based. The RS256 private key never leaves the License Authority. A customer who reads or patches `LicenseMiddleware.php` still cannot:
- Forge a valid JWT (no private key)
- Bypass heartbeat HMAC validation (no server-side secret)
- Avoid hard-block on next heartbeat (server validates independently)

The only scenario obfuscation helps is a customer who manually removes the `check()` call from their own codebase. Section 15 rule 5 covers this: every feature must be gated at the API route level, not only via middleware.

**Actions:**
- Delete `infra/ioncube-encode.sh` and `infra/ioncube-test.sh`
- Delete `infra/README-ioncube.md`
- Strike ionCube items from CLAUDE.md checklist (Section 12.2)
- Update OD-4 in CLAUDE.md: `Closed — ionCube dropped. Obfuscation not required given cryptographic enforcement model.`

---

## Section 3 — Infrastructure Gap: Satis (PHP Registry)

**Status:** Verdaccio (Node) is present and configured. Satis (PHP) is not.

Without Satis, PHP customers cannot `composer require zenplatform/zlf-php` through the private registry as specified in Section 9.3. They would have to install the SDK manually or via a public path.

**What's needed:**

1. Add a `satis` service to `infra/docker-compose.yml`:
```yaml
satis:
  image: composer/satis:latest
  restart: always
  ports:
    - "0.0.0.0:7400:80"
  volumes:
    - ./satis/satis.json:/var/www/satis.json:ro
    - satis-output:/var/www/output
    - ./satis/auth.json:/root/.composer/auth.json:ro
```

2. Create `infra/satis/satis.json`:
```json
{
  "name": "zenplatform/packages",
  "homepage": "https://packages.yourdomain.com",
  "repositories": [
    { "type": "path", "url": "/var/www/sdk-php" }
  ],
  "require-all": true
}
```

3. Add `satis-output` to the `volumes:` block in `docker-compose.yml`.

4. Document customer `composer.json` setup in `docs/sdk-php.md` (already partially written).

---

## Section 4 — Minor Items

These are low-risk but worth cleaning up.

| Item | File | Fix |
|---|---|---|
| `cryptography` not in requirements.txt | `authority/requirements.txt` | Add `cryptography>=41.0` explicitly — it's an implicit dep of python-jose but should be declared |
| `shared_secret_nonce` column is redundant | `authority/app/models.py`, migrations | The nonce is embedded in the encrypted blob; the column is unused in `decrypt_secret()`. Leave it for now (removing needs a migration), but don't rely on it |
| Node `TokenCache.set()` drops machine_id on heartbeat refresh | `sdk-node/src/agent.ts` | `agent.ts` calls `cache.set(token, secret)` without machineId. In-memory value survives (singleton), but disk file loses it on refresh. Pass `cache.getMachineId() ?? undefined` as the third arg |

---

## Section 5 — Completion Checklist

Work remaining, in priority order:

### Priority 1 — Fix before any CI/testing
- [x] Bug 1: Add `machine_id` to `_heartbeat_payload()` in `tests/test_integration.py`
- [x] Bug 2: Patch `DASHBOARD_TOKEN` env and add auth header in `test_dashboard_stats`
- [x] Bug 3: Fix PHP unit test assertion for expired token → `EXPIRED` not `INVALID`
- [x] Bug 4: Replace `random.choices` with `secrets.choice` in `dashboard.py`

### Priority 2 — Infrastructure
- [x] Add Satis service to `infra/docker-compose.yml`
- [x] Create `infra/satis/satis.json`
- [x] Add `satis-output` volume
- [x] Verify `docs/sdk-php.md` has correct Satis customer setup instructions — already complete, no changes needed

### Priority 3 — Cleanup
- [x] Delete ionCube scripts (`infra/ioncube-encode.sh`, `infra/ioncube-test.sh`, `infra/README-ioncube.md`)
- [x] Update CLAUDE.md: close OD-4, strike ionCube checklist items
- [x] Add `cryptography>=41.0` to `authority/requirements.txt`
- [x] Fix Node `TokenCache` to preserve `machine_id` on heartbeat refresh

### Priority 4 — Phase 4 (ZenMSP Migration)
- [x] Review `docs/migration-zenmsp.md` for completeness — updated 2026-07-02
- [ ] Run full integration test suite against a live PostgreSQL instance
- [ ] Execute migration plan on ZenMSP staging environment
- [ ] Confirm ZenMSP middleware replaced: old ZLF → ZLP PHP SDK

---

## Section 6 — What Does NOT Need Work

The following were flagged or questioned during review and are confirmed correct:

| Item | Status |
|---|---|
| HMAC signing parity PHP vs Node | ✅ Identical logic, same key encoding |
| Public key embedded in both SDKs | ✅ Exact same PEM in both — verified |
| All 8 non-negotiable rules | ✅ All enforced |
| Snaglist C1–C4, M1–M3, L1–L2 | ✅ All implemented and verified |
| Hard block on server unreachable | ✅ 3 retries → BLOCKED file → HTTP 402 |
| Secret rotation every heartbeat | ✅ New secret generated, encrypted, stored, returned |
| HTTP 402 for all license failures | ✅ Consistent across both SDKs and all states |
| Dashboard auth (bearer token) | ✅ All `/dashboard/*` routes protected |
| Anomaly scoring and auto-block | ✅ Scheduler running, thresholds correct (0.6 alert, 0.85 auto-block) |
| Billing / invoice / renewal flow | ✅ Complete — PayFast + PayPal webhooks, invoice emails, key activation on first payment |

---

*Generated from full codebase audit — ZLP 2026-07-02*
