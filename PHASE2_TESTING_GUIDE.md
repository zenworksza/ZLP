# Phase 2 Fixes — Testing Guide

**Updated:** 2026-06-11  
**Focus:** Verify all Phase 2 fixes work correctly

---

## Setup

### 1. Apply Database Migration

```bash
cd /home/mdb/workspaces/ZLP/authority
alembic upgrade head
```

This adds:
- `installs.shared_secret_encrypted` (string)
- `installs.shared_secret_nonce` (string)

Verify:
```bash
psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='installs' ORDER BY ordinal_position;"
```

Should show new columns in the list.

---

## Test 1: Activation with Secret Storage

**Goal:** Verify shared secret is encrypted and stored during activation

### Steps

1. Start License Authority:
   ```bash
   cd authority
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. Create a test license key:
   ```bash
   psql -c "
   INSERT INTO products (id, name, slug) VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Test', 'test');
   INSERT INTO license_keys (id, product_id, key, plan, seats, status)
   VALUES ('550e8400-e29b-41d4-a716-446655440001', '550e8400-e29b-41d4-a716-446655440000', 'ZLP-TEST-TEST-0001', 'professional', 10, 'active');
   "
   ```

3. Activate a license:
   ```bash
   curl -X POST http://localhost:8000/v1/activate \
     -H "Content-Type: application/json" \
     -d '{
       "license_key": "ZLP-TEST-TEST-0001",
       "install_id": "550e8400-e29b-41d4-a716-446655440099",
       "domain": "app.test.com",
       "fingerprint": "abc123def456",
       "machine_id": "machine-001",
       "product": "test",
       "version": "1.0.0"
     }'
   ```

4. Verify response includes `shared_secret`:
   ```json
   {
     "shared_secret": "base64-encoded-32-bytes",
     "registry_token": "npm_...",
     "token": "<JWT>"
   }
   ```

5. Check database:
   ```bash
   psql -c "
   SELECT install_id, shared_secret_encrypted, shared_secret_nonce 
   FROM installs 
   WHERE install_id='550e8400-e29b-41d4-a716-446655440099';
   "
   ```

**Expected:** Both encrypted and nonce columns contain data (not empty)

---

## Test 2: HMAC Signature Validation

**Goal:** Verify heartbeat endpoint validates signature and rejects invalid signatures

### Setup

From Test 1, capture:
- `shared_secret` (plaintext) from activation response
- `install_id` = `550e8400-e29b-41d4-a716-446655440099`

### Test 2a: Valid Signature

```bash
# Build payload
INSTALL_ID="550e8400-e29b-41d4-a716-446655440099"
SHARED_SECRET="<base64-from-activation-response>"
TIMESTAMP=$(date +%s)

PAYLOAD='{"install_id":"'$INSTALL_ID'","license_key":"ZLP-TEST-TEST-0001","product":"test","version":"1.0.0","domain":"app.test.com","fingerprint":"abc123def456","timestamp":'$TIMESTAMP',"nonce":"abc123"}'

# Sign with HMAC-SHA256
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SHARED_SECRET" -hex | cut -d' ' -f2)

# Send heartbeat
curl -X POST http://localhost:8000/v1/heartbeat \
  -H "Content-Type: application/json" \
  -H "X-ZLF-Signature: $SIGNATURE" \
  -H "X-ZLF-Timestamp: $TIMESTAMP" \
  -d "$PAYLOAD"
```

**Expected Response:**
```json
{
  "status": "valid",
  "token": "<new-JWT>",
  "shared_secret": "<new-base64-secret>"
}
```

### Test 2b: Invalid Signature

Use same payload but wrong signature:

```bash
# Same setup as 2a, but use wrong signature
WRONG_SIGNATURE="0000000000000000000000000000000000000000000000000000000000000000"

curl -X POST http://localhost:8000/v1/heartbeat \
  -H "Content-Type: application/json" \
  -H "X-ZLF-Signature: $WRONG_SIGNATURE" \
  -H "X-ZLF-Timestamp: $TIMESTAMP" \
  -d "$PAYLOAD"
```

**Expected Response:**
```json
{
  "status": "revoked",
  "reason": "signature_mismatch"
}
```

---

## Test 3: Replay Attack Prevention

**Goal:** Verify same request is rejected within 15-minute window

### Steps

1. Send valid heartbeat (from Test 2a):
   ```bash
   curl -X POST http://localhost:8000/v1/heartbeat \
     -H "Content-Type: application/json" \
     -H "X-ZLF-Signature: $SIGNATURE" \
     -H "X-ZLF-Timestamp: $TIMESTAMP" \
     -d "$PAYLOAD"
   ```

   **Response:** `{"status": "valid", ...}`

2. Immediately send identical request again (same timestamp, same signature, same payload):
   ```bash
   # Same exact request
   curl -X POST http://localhost:8000/v1/heartbeat \
     -H "Content-Type: application/json" \
     -H "X-ZLF-Signature: $SIGNATURE" \
     -H "X-ZLF-Timestamp: $TIMESTAMP" \
     -d "$PAYLOAD"
   ```

   **Expected Response:** `{"status": "revoked", "reason": "replay_attack_detected"}`

3. Verify in database:
   ```bash
   psql -c "
   SELECT timestamp, response_status, payload_hash
   FROM heartbeat_log
   WHERE install_id='550e8400-e29b-41d4-a716-446655440099'
   ORDER BY timestamp DESC
   LIMIT 2;
   "
   ```

   **Expected:** Two entries with same `payload_hash`, one with status `valid`, one with `replay_detected`

---

## Test 4: Secret Rotation

**Goal:** Verify new secrets are returned and stored after each heartbeat

### Steps

1. Do valid heartbeat (Test 2a), capture response:
   ```json
   {
     "status": "valid",
     "token": "<new-JWT-v1>",
     "shared_secret": "<new-secret-v1>"
   }
   ```

2. Use new secret to sign next heartbeat:
   ```bash
   SHARED_SECRET_V2="<new-secret-v1-from-response>"
   TIMESTAMP_V2=$(date +%s)
   
   PAYLOAD_V2='{"install_id":"'$INSTALL_ID'","license_key":"ZLP-TEST-TEST-0001",...,"timestamp":'$TIMESTAMP_V2',...}'
   
   SIGNATURE_V2=$(echo -n "$PAYLOAD_V2" | openssl dgst -sha256 -hmac "$SHARED_SECRET_V2" -hex | cut -d' ' -f2)
   
   curl -X POST http://localhost:8000/v1/heartbeat \
     -H "Content-Type: application/json" \
     -H "X-ZLF-Signature: $SIGNATURE_V2" \
     -H "X-ZLF-Timestamp: $TIMESTAMP_V2" \
     -d "$PAYLOAD_V2"
   ```

   **Expected:** `{"status": "valid", "token": "<new-JWT-v2>", "shared_secret": "<new-secret-v2>"}`

3. Try to use OLD secret:
   ```bash
   SIGNATURE_OLD=$(echo -n "$PAYLOAD_V2" | openssl dgst -sha256 -hmac "$SHARED_SECRET" -hex | cut -d' ' -f2)
   
   curl -X POST http://localhost:8000/v1/heartbeat \
     -H "Content-Type: application/json" \
     -H "X-ZLF-Signature: $SIGNATURE_OLD" \
     -H "X-ZLF-Timestamp: $TIMESTAMP_V2" \
     -d "$PAYLOAD_V2"
   ```

   **Expected:** `{"status": "revoked", "reason": "signature_mismatch"}` (old secret doesn't match)

---

## Test 5: PHP SDK Cache Updates

**Goal:** Verify PHP SDK reads/writes token + secret to cache

### Setup

Assume PHP SDK installed and middleware integrated.

### Steps

1. Activate and capture `shared_secret`:
   ```bash
   # (same as Test 1, step 3)
   ```

2. Check cache file:
   ```bash
   cat /var/lib/zlp/test/550e8400-e29b-41d4-a716-446655440099.cache | jq .
   ```

   **Expected:**
   ```json
   {
     "token": "<JWT>",
     "shared_secret": "base64-secret",
     "cached_at": 1718000000
   }
   ```

3. Run agent daemon:
   ```bash
   export ZLP_INSTALL_ID="550e8400-e29b-41d4-a716-446655440099"
   export ZLP_LICENSE_KEY="ZLP-TEST-TEST-0001"
   export ZLP_PRODUCT="test"
   export ZLP_DOMAIN="app.test.com"
   export ZLP_FINGERPRINT="abc123def456"
   
   php vendor/bin/zlp-agent heartbeat
   ```

4. Check cache again:
   ```bash
   cat /var/lib/zlp/test/550e8400-e29b-41d4-a716-446655440099.cache | jq .
   ```

   **Expected:** New `shared_secret` and `token` (different from before)

---

## Test 6: Node SDK Cache Updates

**Goal:** Verify Node SDK reads/writes token + secret to cache

### Setup

Assume Node SDK installed and middleware integrated.

### Steps

1. Same as Test 5, but for Node environment:
   ```bash
   export ZLP_INSTALL_ID="550e8400-e29b-41d4-a716-446655440099"
   export ZLP_LICENSE_KEY="ZLP-TEST-TEST-0001"
   export ZLP_PRODUCT="test"
   export DATA_DIR="/var/lib/zlp"
   
   # Start Next.js app with instrumentation.ts containing:
   # import { startLicenseAgent } from '@zenplatform/zlf-node';
   # startLicenseAgent({ product: 'test' });
   ```

2. Check cache:
   ```bash
   cat /var/lib/zlp/test/token.cache | jq .
   ```

   **Expected:** Same JSON format as PHP, with token + shared_secret

---

## Cleanup

```bash
# Revert database (if needed)
alembic downgrade 001

# Delete test cache files
rm -rf /var/lib/zlp/test

# Delete test license data
psql -c "
DELETE FROM license_keys WHERE key LIKE 'ZLP-TEST-%';
DELETE FROM products WHERE slug = 'test';
"
```

---

## Troubleshooting

### "Signature mismatch" on valid request

- Verify HMAC is computed from **raw request JSON**, not pretty-printed
- Verify shared_secret is base64 string, not decoded bytes
- Check timestamp is within 300s of server time

### Heartbeat endpoint returns 500 error

- Check logs for decryption errors: `decrypt_secret() failed`
- Verify `shared_secret_encrypted` and `shared_secret_nonce` are populated
- Try reinitializing install table with fresh activation

### "Install not found" on heartbeat

- Verify install_id is correct
- Check database: `SELECT * FROM installs WHERE install_id='...'`
- May need to reactivate if install record was deleted

### Replay attack not detected

- Verify same exact JSON payload (character-for-character)
- Verify heartbeat timestamps are close (within 1 second)
- Check heartbeat_log: both requests should have identical `payload_hash`

---

## Summary Checklist

- [ ] Migration applied (`alembic upgrade head`)
- [ ] Test 1: Activation stores encrypted secret
- [ ] Test 2a: Valid signature accepted
- [ ] Test 2b: Invalid signature rejected
- [ ] Test 3: Replay attack detected
- [ ] Test 4: Secret rotation works
- [ ] Test 5: PHP SDK updates cache correctly
- [ ] Test 6: Node SDK updates cache correctly

If all tests pass, Phase 2 fixes are complete and ready for Phase 3.

---

Generated by Claude  
2026-06-11 | ZLP Phase 2 Testing
