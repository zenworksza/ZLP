# ZLP Key Management

**Status:** Phase 1 | Generated: 2026-06-05

## Overview

ZLP uses asymmetric cryptography (RS256) for token signing and HMAC-SHA256 for heartbeat request validation. This document describes key generation, storage, rotation, and usage.

---

## 1. RS256 Keypair (JWT Signing)

### 1.1 Generation

RS256 keypair generated 2026-06-05:

```bash
openssl genrsa -out zlp_private.pem 2048
openssl rsa -in zlp_private.pem -pubout -out zlp_public.pem
```

**Key size:** 2048-bit RSA (standard for production JWT signing per JOSE / JWT.io best practices)

### 1.2 Private Key Storage

**Location:** `/infra/keys/zlp_private.pem` (NOT in version control)

**Access control:**
- Readable only by License Authority application (mode 0400)
- Never distributed, never shared
- Encrypted at rest in production (AWS Secrets Manager or equivalent)
- Rotated annually or on suspected compromise

**Environment variable:** `JWT_PRIVATE_KEY_PATH=/infra/keys/zlp_private.pem`

**In Docker Compose:** Mounted as read-only secret:
```yaml
secrets:
  jwt_private:
    file: ./infra/keys/zlp_private.pem
```

### 1.3 Public Key Distribution

**Location:** `/infra/keys/zlp_public.pem`

**Embedded in SDKs as constant string (never fetched at runtime):**

**PHP SDK** (`sdk-php/config/zlp_public.pem`):
```php
const PUBLIC_KEY = <<<'EOK'
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6qKYVAq3Gx77hsPPbFJF
BkogBDo7wVnXamjANNMQDkzHg3kR1Maru+hpytiaYNG62ydhl7qjSFin/4n0saxq
gk2aHLzkG2xPJZl8MailMMQbjpCrVIi3cI9ARpVbwWuLPA5Zu1hfU2G0AKWWn7yE
xqzuUeoy07nu9s320Xzzsdd4zfOvwQvdvcFnWr3VwEbjjKB+dqpeLWYQ8cdYc66+
VW6PtrxLlg45ujIRThiXhJpc4QhV7GPSpAY/sW6UjKtmCbgvRxjfycxIvQoP3Au7
06PmicqsC/94A/g/tgNFfcy0RYqpM89OwCQjz4eC+Nygx0kgjZ0x+5da0ALUHfcz
XwIDAQAB
-----END PUBLIC KEY-----
EOK;
```

**Node SDK** (`sdk-node/src/keys/zlp_public.pem`):
```typescript
export const PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6qKYVAq3Gx77hsPPbFJF
BkogBDo7wVnXamjANNMQDkzHg3kR1Maru+hpytiaYNG62ydhl7qjSFin/4n0saxq
gk2aHLzkG2xPJZl8MailMMQbjpCrVIi3cI9ARpVbwWuLPA5Zu1hfU2G0AKWWn7yE
xqzuUeoy07nu9s320Xzzsdd4zfOvwQvdvcFnWr3VwEbjjKB+dqpeLWYQ8cdYc66+
VW6PtrxLlg45ujIRThiXhJpc4QhV7GPSpAY/sW6UjKtmCbgvRxjfycxIvQoP3Au7
06PmicqsC/94A/g/tgNFfcy0RYqpM89OwCQjz4eC+Nygx0kgjZ0x+5da0ALUHfcz
XwIDAQAB
-----END PUBLIC KEY-----`;
```

### 1.4 Key Rotation Schedule

**Rotation trigger:** Annually (every 12 months) OR on suspected compromise

**Rotation procedure:**

1. **Generate new keypair** at License Authority:
   ```bash
   openssl genrsa -out zlp_private_v2.pem 2048
   openssl rsa -in zlp_private_v2.pem -pubout -out zlp_public_v2.pem
   ```

2. **Overlap period** (30 days):
   - License Authority signs new tokens with `zlp_private_v2`
   - License Authority still accepts tokens signed with `zlp_private` (previous key)
   - SDKs continue accepting tokens signed with embedded `zlp_public` (old key)

3. **New SDK version**:
   - Embed new public key (`zlp_public_v2`) in new SDK release
   - Publish to Satis (PHP) and Verdaccio (Node)
   - Update activation endpoint to distribute new SDK version

4. **Deprecation** (after 30-day overlap):
   - License Authority stops accepting tokens signed with old private key
   - Customers must upgrade to new SDK version
   - Old SDK versions will fail to verify new tokens (by design — forces upgrade)

**Timeline:**
- Day 0: Generate new keypair, begin overlap
- Day 1: New SDK version released with new public key
- Day 30: Stop accepting tokens from old private key
- Day 31: Old SDK versions cannot activate (must upgrade)

### 1.5 Key Compromise Response

If private key is compromised:
1. **Immediate action:** Revoke all issued tokens and force immediate heartbeat
2. **Generate new keypair** immediately (out of rotation schedule)
3. **Release emergency SDK update** with new public key (marked urgent in registry)
4. **Monitor** for suspicious activations / token reuse

---

## 2. Shared Secret (Heartbeat HMAC)

### 2.1 Generation

**When:** During `/v1/activate` response

**What:** Cryptographically random 32-byte string (256-bit), base64-encoded

```python
import secrets
import base64

shared_secret_bytes = secrets.token_bytes(32)
shared_secret_b64 = base64.b64encode(shared_secret_bytes).decode('ascii')
```

**Usage:** SDK uses this to sign heartbeat requests with HMAC-SHA256

```python
import hmac
import hashlib
import json

payload = json.dumps({...})
signature = hmac.new(
    base64.b64decode(shared_secret),
    payload.encode(),
    hashlib.sha256
).hexdigest()
```

### 2.2 Rotation Protocol

**Rotation:** On every successful heartbeat response

**Kimi implements in `/v1/heartbeat` response:**

```json
{
  "status": "valid",
  "token": "<JWT>",
  "shared_secret": "<new-base64-secret>"
}
```

**Why:** Captures HMAC in transit prevents replay attacks. If a heartbeat request is captured on the network, the shared_secret is immediately rotated, making the captured request non-replayable.

**SDK behavior:**
1. SDK sends heartbeat with old secret
2. License Authority validates signature with old secret
3. License Authority returns new secret in response
4. SDK updates its cached secret for next heartbeat
5. Old secret is now invalid

**Maximum replay window:** 1 heartbeat interval (15 min). After next successful heartbeat, stolen request becomes useless.

---

## 3. Activation Secret (Machine Binding)

### 3.1 Definition

Used to derive machine-bound fingerprint per CLAUDE.md Section 5.1.

```
fingerprint = HMAC-SHA256(
  install_id + ":" + domain + ":" + machine_id,
  activation_secret
)
```

### 3.2 Generation

**When:** During `/v1/activate` response

**What:** Cryptographically random 32-byte string (256-bit), base64-encoded

```python
activation_secret = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
```

**Storage:** Sent to customer's install in `/v1/activate` response (one-time, during activation only)

```json
{
  "shared_secret": "...",
  "registry_token": "...",
  "token": "...",
  "activation_secret": "<base64-secret>"
}
```

**SDK stores:** In machine-bound cache (encrypted with key derived from install_id + machine_id)

### 3.3 Rotation Protocol

**Rotation:** On request of customer OR on detected anomaly (fingerprint drift)

**Process:**
1. Vendor calls `/v1/rotate-activation-secret/{install_id}` (not yet implemented, Phase 3)
2. License Authority generates new activation_secret
3. Next heartbeat returns rotated activation_secret
4. SDK updates cache with new secret
5. Next activation check uses new secret for fingerprint validation

**Immutable:** Activation secret does NOT rotate on every heartbeat (unlike shared_secret). It persists across heartbeat cycles to enable fingerprint verification.

---

## 4. Database Key Storage

**Never stored in database.** Keys remain in memory / environment only.

**Why:** Database compromises would expose all keys. Storing only hashes would break JWT signing (we need the actual private key).

**Exception:** `shared_secret` hash can optionally be logged for audit purposes (compare against heartbeat request), but not the actual secret value.

---

## 5. Development vs Production

### 5.1 Development

```bash
# In /infra/keys/
zlp_private.pem       # Checked in for local testing (NOT SECURE FOR PROD)
zlp_public.pem        # Checked in, embedded in SDKs
```

**Note:** Development keys are shared in the repo. This is acceptable for internal testing only.

### 5.2 Production

```bash
# Private key in AWS Secrets Manager / HashiCorp Vault
# Access via:
export JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem  # Docker Compose secret
# OR
export JWT_PRIVATE_KEY=$(aws secretsmanager get-secret-value --secret-id zlp/jwt-private --query SecretString --output text)
```

**Audit:** Every private key operation is logged (key access, rotation, etc).

---

## 6. Certificate Pinning (Future)

If customer needs extra protection against MITM attacks on heartbeat, consider:

1. Certificate pinning: SDK pins License Authority's TLS certificate
2. Key pinning: SDK pins public key + signature algorithm
3. Fallback: Soft fail (warn) on certificate mismatch, hard fail on key mismatch

**Not implemented in Phase 1.** Flag if customers request.

---

## 7. Checklist for Implementers

### Kimi (License Authority Backend)

- [ ] Store private key in `/infra/keys/zlp_private.pem` (mode 0400)
- [ ] Load private key from `JWT_PRIVATE_KEY_PATH` environment variable at startup
- [ ] Sign JWTs in `/v1/activate` and `/v1/heartbeat` using `python-jose` library
- [ ] Validate `X-ZLF-Signature` header in `/v1/heartbeat` using shared_secret
- [ ] Rotate shared_secret in every successful `/v1/heartbeat` response
- [ ] Log all key operations (access, rotation, error) to audit trail

### Gemini (Node SDK)

- [ ] Embed public key in `sdk-node/src/keys/zlp_public.pem`
- [ ] Verify JWT signatures using `jose` library
- [ ] Cache activation_secret from `/v1/activate` response
- [ ] Store shared_secret from activation/heartbeat responses
- [ ] Sign heartbeat payload with `HMAC-SHA256(payload, shared_secret)`
- [ ] Include `X-ZLF-Signature` and `X-ZLF-Timestamp` headers in heartbeat POST
- [ ] Update shared_secret from heartbeat response before next cycle

### Kimi (PHP SDK)

- [ ] Embed public key in `sdk-php/config/zlp_public.pem`
- [ ] Verify JWT signatures using `firebase/php-jwt` library
- [ ] Same secret/signature handling as Node SDK

---

## 8. Testing Keys

For unit/integration testing, use these development keys (included in repo):

```
zlp_private.pem (test key, not secure)
zlp_public.pem  (test key, matches private key)
```

**Do NOT use these in production.** Generate new keys for production deployment.

---

## Appendix: Key Formats

### PKCS#1 vs PKCS#8

Generated keys are in PKCS#1 format (traditional):
```
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

To convert to PKCS#8 (if needed for certain libraries):
```bash
openssl pkcs8 -topk8 -inform PEM -outform PEM -in zlp_private.pem -out zlp_private_pkcs8.pem
```

**Current choice:** PKCS#1 (works with python-jose and firebase/php-jwt out of the box)

---

## Appendix: Key Details

```
Key size: 2048-bit RSA
Algorithm: RS256 (RSASSA-PKCS1-v1_5 with SHA-256)
Created: 2026-06-05
Fingerprint: [stored in secure location only]
Next rotation: 2027-06-05 (12 months)
```
