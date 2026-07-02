"""License activation endpoint"""
import os
import secrets
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from jose import jwt, JWTError
import logging

from sqlalchemy import func
from ..models import LicenseKey, Install, Product, AuditTrail
from ..database import get_db
from ..crypto import encrypt_secret
from ..plan_config import fetch_features

logger = logging.getLogger(__name__)

router = APIRouter()

# Configuration
JWT_PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", "/home/mdb/workspaces/ZLP/infra/keys/zlp_private.pem")
JWT_ALGORITHM = "RS256"
JWT_ISSUER = "zlp.yourdomain.com"
JWT_TTL_SECONDS = 1800  # 30 minutes
REGISTRY_TOKEN_PREFIX = "npm_"


class ActivateRequest(BaseModel):
    license_key: str
    install_id: str
    domain: str
    fingerprint: str
    machine_id: str
    product: str
    version: str


class ActivateResponse(BaseModel):
    shared_secret: str
    registry_token: str
    token: str


class ErrorResponse(BaseModel):
    status: str = "error"
    error: str
    message: str


def load_private_key() -> str:
    """Load RSA private key from file"""
    try:
        with open(JWT_PRIVATE_KEY_PATH, 'r') as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"Private key not found at {JWT_PRIVATE_KEY_PATH}")


def generate_jwt(license_key: LicenseKey, install: Install, install_id: str, features: list[str]) -> str:
    """Generate RS256 JWT token"""
    private_key = load_private_key()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=JWT_TTL_SECONDS)

    payload = {
        "iss": JWT_ISSUER,
        "sub": f"install:{install_id}",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "license_key": license_key.key,
        "product": license_key.product.slug,
        "plan": license_key.plan,
        "seats": license_key.seats,
        "features": features,
        "domain": install.domain,
        "install_id": install_id,
        "revoked": False,
        "server_time": int(now.timestamp()),  # C1: SDK validates local clock against this
    }

    return jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)



def generate_shared_secret() -> tuple[str, str]:
    """Generate a 32-byte random secret and return (raw_bytes, base64_string)"""
    secret_bytes = secrets.token_bytes(32)
    secret_b64 = base64.b64encode(secret_bytes).decode('ascii')
    return secret_bytes, secret_b64


def generate_registry_token() -> str:
    """Generate a bearer token for package registry access"""
    token_bytes = secrets.token_bytes(24)
    token_hex = token_bytes.hex()
    return f"{REGISTRY_TOKEN_PREFIX}{token_hex}"


@router.post("/activate", response_model=ActivateResponse)
async def activate_license(
    request: ActivateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActivateResponse:
    """
    Activate a license on a new install.

    Returns RS256 JWT, shared_secret for heartbeat HMAC, and registry_token for package access.
    """

    # L1: Rate-limit failed activation attempts — max 5 per key per hour
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    fail_count_result = await db.execute(
        select(func.count()).select_from(AuditTrail).where(
            AuditTrail.action == "activate_failed",
            AuditTrail.target_id == request.license_key,
            AuditTrail.timestamp > one_hour_ago,
        )
    )
    if (fail_count_result.scalar() or 0) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ErrorResponse(
                error="too_many_attempts",
                message="Too many failed activation attempts. Try again in an hour.",
            ).model_dump(),
        )

    # Validate license key exists and is active
    stmt = select(LicenseKey).options(selectinload(LicenseKey.product)).where(LicenseKey.key == request.license_key)
    result = await db.execute(stmt)
    license_key = result.scalar_one_or_none()

    async def _fail(error: str, message: str, http_status: int) -> None:
        """Log a failed activation attempt and raise."""
        logger.warning(f"Activation failed: {error} - {request.license_key}")
        db.add(AuditTrail(
            actor="system",
            action="activate_failed",
            target_type="license_key",
            target_id=request.license_key,
            timestamp=datetime.now(timezone.utc),
            meta={"error": error, "domain": request.domain, "install_id": request.install_id},
        ))
        await db.commit()
        raise HTTPException(
            status_code=http_status,
            detail=ErrorResponse(error=error, message=message).model_dump(),
        )

    if not license_key:
        await _fail("key_not_found", f"License key {request.license_key} does not exist", status.HTTP_404_NOT_FOUND)

    # Check if key is expired
    if license_key.expires_at and license_key.expires_at < datetime.now(timezone.utc):
        await _fail("license_expired", "License key is expired", status.HTTP_402_PAYMENT_REQUIRED)

    # Check if key is revoked, suspended, or pending payment
    if license_key.status in ["revoked", "suspended", "pending"]:
        await _fail("license_invalid", f"License key is {license_key.status}", status.HTTP_402_PAYMENT_REQUIRED)

    # L1: Check for domain mismatch - if this key already has an install on a different domain
    existing_stmt = select(Install).where(Install.key_id == license_key.id)
    existing_result = await db.execute(existing_stmt)
    existing_install = existing_result.scalar_one_or_none()

    if existing_install and existing_install.domain != request.domain:
        await _fail(
            "domain_mismatch",
            f"Key already activated on {existing_install.domain}",
            status.HTTP_409_CONFLICT,
        )

    # Generate response components
    secret_bytes, shared_secret_b64 = generate_shared_secret()
    registry_token = generate_registry_token()

    # Encrypt shared secret for storage
    encrypted_secret, nonce_hex = encrypt_secret(request.install_id, shared_secret_b64)

    client_ip = http_request.client.host if http_request.client else None

    # Create or update install record
    if existing_install:
        install = existing_install
        install.shared_secret_encrypted = encrypted_secret
        install.shared_secret_nonce = nonce_hex
        install.registered_ip = client_ip
    else:
        install = Install(
            key_id=license_key.id,
            install_id=request.install_id,
            domain=request.domain,
            fingerprint=request.fingerprint,
            machine_id=request.machine_id,
            status="active",
            registered_ip=client_ip,
            shared_secret_encrypted=encrypted_secret,
            shared_secret_nonce=nonce_hex,
        )
        db.add(install)

    await db.commit()
    await db.refresh(install)

    features = await fetch_features(db, license_key.product.slug, license_key.plan)
    token = generate_jwt(license_key, install, request.install_id, features)

    db.add(AuditTrail(
        actor="system",
        action="activate_success",
        target_type="license_key",
        target_id=request.license_key,
        timestamp=datetime.now(timezone.utc),
        meta={"domain": request.domain, "install_id": request.install_id},
    ))
    await db.commit()
    logger.info(f"Activation successful: {request.install_id} on {request.domain}")

    return ActivateResponse(
        shared_secret=shared_secret_b64,
        registry_token=registry_token,
        token=token,
    )
