"""Encryption utilities for storing secrets in database"""
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def derive_encryption_key(install_id: str, salt: bytes) -> bytes:
    """Derive a 32-byte encryption key from install_id using PBKDF2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return kdf.derive(install_id.encode('utf-8'))


def encrypt_secret(install_id: str, secret: str) -> tuple[str, str]:
    """
    Encrypt a secret (base64 string) using AES-256-GCM.
    Returns (encrypted_base64, nonce_base64)
    """
    # Generate salt and nonce
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)

    # Derive key from install_id
    key = derive_encryption_key(install_id, salt)

    # Create cipher and encrypt
    cipher = AESGCM(key)
    plaintext = secret.encode('utf-8')
    ciphertext = cipher.encrypt(nonce, plaintext, None)

    # Encode: nonce || salt || ciphertext as one base64 blob
    combined = nonce + salt + ciphertext
    encrypted_b64 = base64.b64encode(combined).decode('ascii')

    return encrypted_b64, nonce.hex()


def decrypt_secret(install_id: str, encrypted_b64: str) -> str:
    """
    Decrypt a secret encrypted with encrypt_secret.
    Returns the original secret (base64 string).
    """
    combined = base64.b64decode(encrypted_b64)

    # Extract nonce (first 12 bytes), salt (next 16 bytes), ciphertext (rest)
    nonce = combined[:12]
    salt = combined[12:28]
    ciphertext = combined[28:]

    # Derive key from install_id
    key = derive_encryption_key(install_id, salt)

    # Decrypt
    cipher = AESGCM(key)
    plaintext = cipher.decrypt(nonce, ciphertext, None)

    return plaintext.decode('utf-8')
