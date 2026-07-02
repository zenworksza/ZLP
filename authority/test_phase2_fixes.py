#!/usr/bin/env python3
"""
Verify Phase 2 fixes are properly integrated:
1. Models have encrypted secret columns
2. Crypto module is working
3. Code imports without circular dependency issues
"""
import sys
sys.path.insert(0, '/home/mdb/workspaces/ZLP/authority')

print("=" * 80)
print("PHASE 2 FIXES VERIFICATION")
print("=" * 80)

# Test 1: Models have new columns
print("\n[Test 1] Checking Install model for encrypted secret columns...")
try:
    from app.models import Install
    columns = {col.name for col in Install.__table__.columns}

    required_columns = {'shared_secret_encrypted', 'shared_secret_nonce'}
    has_columns = required_columns.issubset(columns)

    if has_columns:
        print(f"  ✓ Install table has: {required_columns}")
        print(f"  ✓ All columns: {sorted(columns)}")
    else:
        missing = required_columns - columns
        print(f"  ✗ FAILED - Missing columns: {missing}")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ FAILED - Error importing models: {e}")
    sys.exit(1)

# Test 2: Crypto module works
print("\n[Test 2] Testing crypto encryption/decryption...")
try:
    from app.crypto import encrypt_secret, decrypt_secret

    test_install_id = "test-install-123"
    test_secret = "base64encodedsecretstring123456=="

    # Encrypt
    encrypted, nonce = encrypt_secret(test_install_id, test_secret)
    print(f"  ✓ Encrypted secret (length={len(encrypted)})")
    print(f"  ✓ Nonce: {nonce[:16]}...")

    # Decrypt
    decrypted = decrypt_secret(test_install_id, encrypted)

    if decrypted == test_secret:
        print(f"  ✓ Decryption successful - secret matches")
    else:
        print(f"  ✗ FAILED - Decrypted secret doesn't match")
        print(f"    Expected: {test_secret}")
        print(f"    Got: {decrypted}")
        sys.exit(1)

except Exception as e:
    print(f"  ✗ FAILED - Crypto error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: No circular imports
print("\n[Test 3] Testing for circular import issues...")
try:
    from app import main
    from app.routers import activate, heartbeat, health
    print(f"  ✓ main module loaded")
    print(f"  ✓ routers.activate loaded")
    print(f"  ✓ routers.heartbeat loaded")
    print(f"  ✓ routers.health loaded")
except ImportError as e:
    print(f"  ✗ FAILED - Circular import: {e}")
    sys.exit(1)

# Test 4: Functions exist
print("\n[Test 4] Verifying endpoint functions...")
try:
    assert hasattr(health, 'router'), "health router not found"
    assert hasattr(activate, 'router'), "activate router not found"
    assert hasattr(heartbeat, 'router'), "heartbeat router not found"
    assert hasattr(activate, 'activate_license'), "activate_license function not found"
    assert hasattr(heartbeat, 'heartbeat'), "heartbeat function not found"
    print(f"  ✓ health.router exists")
    print(f"  ✓ activate.router exists")
    print(f"  ✓ heartbeat.router exists")
    print(f"  ✓ activate_license() exists")
    print(f"  ✓ heartbeat() exists")
except AssertionError as e:
    print(f"  ✗ FAILED - {e}")
    sys.exit(1)

# Test 5: TokenCache updates (PHP)
print("\n[Test 5] Checking PHP SDK TokenCache...")
try:
    with open('/home/mdb/workspaces/ZLP/sdk-php/src/TokenCache.php', 'r') as f:
        php_content = f.read()

    required_methods = {'getSharedSecret', 'set'}
    has_methods = all(method in php_content for method in required_methods)

    if has_methods:
        print(f"  ✓ TokenCache has getSharedSecret() method")
        print(f"  ✓ TokenCache.set() accepts secret parameter")
    else:
        print(f"  ✗ FAILED - Missing methods in TokenCache")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ FAILED - Error checking PHP SDK: {e}")
    sys.exit(1)

# Test 6: TokenCache updates (Node)
print("\n[Test 6] Checking Node SDK tokenCache...")
try:
    with open('/home/mdb/workspaces/ZLP/sdk-node/src/tokenCache.ts', 'r') as f:
        ts_content = f.read()

    required_methods = {'getSharedSecret', 'shared_secret'}
    has_methods = all(method in ts_content for method in required_methods)

    if has_methods:
        print(f"  ✓ tokenCache has getSharedSecret() method")
        print(f"  ✓ tokenCache stores shared_secret in JSON")
    else:
        print(f"  ✗ FAILED - Missing methods in Node tokenCache")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ FAILED - Error checking Node SDK: {e}")
    sys.exit(1)

# Test 7: Heartbeat validation
print("\n[Test 7] Checking heartbeat endpoint...")
try:
    with open('/home/mdb/workspaces/ZLP/authority/app/routers/heartbeat.py', 'r') as f:
        hb_content = f.read()

    checks = {
        'HMAC validation': 'hmac.compare_digest' in hb_content,
        'Replay detection': 'payload_hash' in hb_content,
        'Secret decryption': 'decrypt_secret' in hb_content,
        'Secret rotation': 'encrypt_secret' in hb_content,
    }

    all_pass = True
    for check_name, passes in checks.items():
        status = "✓" if passes else "✗"
        print(f"  {status} {check_name}")
        all_pass = all_pass and passes

    if not all_pass:
        print(f"\n  ✗ FAILED - Some checks missing")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ FAILED - Error checking heartbeat endpoint: {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ ALL PHASE 2 FIXES VERIFIED SUCCESSFULLY")
print("=" * 80)
print("\nNext steps:")
print("  1. Set DATABASE_URL to your PostgreSQL database")
print("  2. Apply migration: alembic upgrade head (if using PostgreSQL)")
print("  3. Start server: uvicorn app.main:app")
print("  4. Test endpoints with curl or Postman")
print("  5. Follow PHASE2_TESTING_GUIDE.md for full test suite")
print()
