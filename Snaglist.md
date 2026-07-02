# ZLP Security Snaglist

All items from the initial architecture review are resolved. Kept here as a record.

---

## ✅ Critical

**C1. Clock manipulation — local `exp` check against attacker-controlled clock**
**Fixed:** `server_time` claim added to every issued JWT (authority). PHP and Node middleware now reject tokens where local clock is 60s+ behind `iat`, or deviates >1920s from `server_time`.

**C2. `shared_secret` stored in plaintext in `token.cache`**
**Fixed:** PHP `TokenCache` now AES-256-GCM encrypts the shared secret using a key derived from `install_id` + `machine_id`. Backward-compatible read of old plaintext files retained.

**C3. BLOCKED file deletion bypasses revocation**
**Fixed:** Heartbeat now checks `install.status == "blocked"` server-side before checking key status — a per-install block cannot be bypassed by deleting the local BLOCKED file.

**C4. `install_id` + token cache cloning**
**Fixed:** Heartbeat compares incoming fingerprint against the value stored at activation. Mismatch → immediate revoke + `AnomalyEvent` at score 0.9.

---

## ✅ Medium

**M1. `alg: none` / algorithm confusion attack**
**Fixed:** PHP: `Key` constructor already pinned RS256 (confirmed + commented). Node: explicit `{ algorithms: ['RS256'] }` added to `jwtVerify`.

**M2. Domain claim not validated at request time**
**Fixed:** Both PHP and Node middleware now compare the incoming `Host` header (port-stripped, lowercased) against the JWT `domain` claim. Mismatch → INVALID / 402.

**M3. Fingerprint not validated locally**
**Fixed:** Both SDKs store `machine_id` in the token cache at activation. Middleware reads and recomputes current `machine_id` on each `check()` — mismatch → INVALID / 402.

---

## ✅ Low

**L1. Activation auth relies solely on `license_key`**
**Fixed:** Activation rate-limited to 5 failures per key per hour, tracked via `AuditTrail`. Each failure and success is now logged.

**L2. `ZLP-XXXX-XXXX-XXXX` key format — insufficient entropy**
**Fixed:** Key format upgraded from `ZLP-XXXX-XXXX-XXXX` (~32 bits) to `ZLP-XXXXXX-XXXXXX-XXXXXX-XXXXXX` (~124 bits).

---

## Baseline — Confirmed Sound

- RS256 asymmetric signing — private key never leaves the authority ✅
- Short JWT TTL (~30 min) — limits stolen-token window ✅
- Nonce + timestamp in heartbeat payload — prevents replay ✅
- `install_id` embedded in JWT — prevents cross-install token reuse ✅
- Middleware never makes a network call ✅
