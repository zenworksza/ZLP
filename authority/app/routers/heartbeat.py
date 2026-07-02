"""Heartbeat validation endpoint - core of licensing enforcement"""
import os
import secrets
import base64
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from jose import jwt
import logging

from ..models import Install, LicenseKey, HeartbeatLog, AnomalyEvent
from ..database import get_db
from .activate import load_private_key, JWT_ALGORITHM, JWT_ISSUER, JWT_TTL_SECONDS
from ..crypto import decrypt_secret
from ..plan_config import fetch_features

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_MAX_AGE = 300  # 5 minutes


class HeartbeatRequest(BaseModel):
    install_id: str
    license_key: str
    product: str
    version: str
    domain: str
    fingerprint: str
    machine_id: str
    timestamp: int
    nonce: str


class HeartbeatResponseValid(BaseModel):
    status: str = "valid"
    token: str
    shared_secret: str


class HeartbeatResponseRevoked(BaseModel):
    status: str
    reason: str


async def validate_signature_and_get_secret(
    install_id: str,
    signature: str,
    body: bytes,
    req_timestamp: int,
    db: AsyncSession = Depends(get_db),
) -> tuple[str, str]:
    """
    Validate timestamp, lookup install, decrypt shared secret, and verify HMAC signature.
    Returns (shared_secret_b64, payload_hash).
    """
    # Validate timestamp (reject if > 300s old)
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - req_timestamp) > HEARTBEAT_MAX_AGE:
        logger.warning(f"Heartbeat rejected: timestamp too old - {abs(now - req_timestamp)}s")
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail={"status": "error", "error": "timestamp_expired", "reason": "Request timestamp too old"},
        )

    # Look up install to decrypt its shared_secret
    stmt = select(Install).where(Install.install_id == install_id)
    result = await db.execute(stmt)
    install = result.scalar_one_or_none()

    if not install:
        logger.warning(f"Heartbeat rejected: install not found - {install_id}")
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail={"status": "error", "error": "install_not_found", "reason": "Install not registered"},
        )

    # Decrypt shared secret from database
    try:
        shared_secret_b64 = decrypt_secret(install_id, install.shared_secret_encrypted)
    except Exception as e:
        logger.error(f"Failed to decrypt shared secret for {install_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail={"status": "error", "error": "decryption_failed", "reason": "Internal error"},
        )

    # Verify HMAC signature
    expected_signature = hmac.new(
        shared_secret_b64.encode('utf-8'),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        logger.warning(f"Heartbeat rejected: invalid signature - {install_id}")
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail={"status": "revoked", "reason": "signature_mismatch"},
        )

    # Compute payload hash for replay prevention
    payload_hash = hashlib.sha256(body).hexdigest()

    return shared_secret_b64, payload_hash


@router.post("/heartbeat")
async def heartbeat(
    http_request: Request,
    signature: str = Header(..., alias="X-ZLF-Signature"),
    req_timestamp: int = Header(..., alias="X-ZLF-Timestamp"),
    db: AsyncSession = Depends(get_db),
):
    """
    Periodic license validation heartbeat.

    Called every 15 minutes by install agent.
    Always returns HTTP 200 (SDK reads 'status' field, not HTTP code).
    """

    # Get raw request body for signature validation
    request_body = await http_request.body()

    # Parse request body into model
    import json
    request_dict = json.loads(request_body)
    request = HeartbeatRequest(**request_dict)

    # Validate signature and get shared secret
    try:
        shared_secret_b64, payload_hash = await validate_signature_and_get_secret(
            request.install_id, signature, request_body, req_timestamp, db
        )
    except HTTPException as e:
        return e.detail

    # Look up install for additional validation
    stmt = select(Install).where(Install.install_id == request.install_id)
    result = await db.execute(stmt)
    install = result.scalar_one_or_none()

    # Look up license key
    stmt = select(LicenseKey).where(LicenseKey.id == install.key_id)
    result = await db.execute(stmt)
    license_key = result.scalar_one_or_none()

    if not license_key:
        logger.warning(f"Heartbeat rejected: license key not found")
        await log_heartbeat(db, request.install_id, "error", None, payload_hash)
        return HeartbeatResponseRevoked(status="error", reason="license_key_not_found")

    # Extract source IP
    source_ip = http_request.client.host if http_request.client else None

    # Validate machine_id matches what was registered at activation
    if install.machine_id and request.machine_id != install.machine_id:
        logger.warning(f"Heartbeat machine_id mismatch - {request.install_id}: got {request.machine_id}, expected {install.machine_id}")
        await log_heartbeat(db, request.install_id, "machine_id_mismatch", None, payload_hash, source_ip)
        db.add(AnomalyEvent(
            install_id=request.install_id,
            score=0.95,
            reason=f"machine_id_mismatch:registered={install.machine_id[:8]}...,received={request.machine_id[:8]}...",
            triggered_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        return HeartbeatResponseRevoked(status="revoked", reason="machine_id_mismatch")

    # Detect concurrent heartbeats from a different IP within the same 15-min window
    # — strongest signal that the token cache has been cloned to another server
    if source_ip and install.registered_ip:
        fifteen_min_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
        concurrent_stmt = select(HeartbeatLog).where(
            HeartbeatLog.install_id == request.install_id,
            HeartbeatLog.source_ip.isnot(None),
            HeartbeatLog.source_ip != source_ip,
            HeartbeatLog.timestamp > fifteen_min_ago,
        )
        concurrent_result = await db.execute(concurrent_stmt)
        concurrent = concurrent_result.scalar_one_or_none()
        if concurrent:
            logger.warning(f"Concurrent heartbeat from different IP - {request.install_id}: {concurrent.source_ip} vs {source_ip}")
            await log_heartbeat(db, request.install_id, "concurrent_ip_mismatch", None, payload_hash, source_ip)
            db.add(AnomalyEvent(
                install_id=request.install_id,
                score=1.0,
                reason=f"concurrent_ip_mismatch:{concurrent.source_ip} vs {source_ip}",
                triggered_at=datetime.now(timezone.utc),
            ))
            await db.commit()
            return HeartbeatResponseRevoked(status="revoked", reason="concurrent_ip_mismatch")

    # C3: Check install-level block (independent of key status — covers per-install blocks)
    if install.status == "blocked":
        logger.warning(f"Heartbeat revoked: install blocked - {request.install_id}")
        await log_heartbeat(db, request.install_id, "revoked", None, payload_hash, source_ip)
        return HeartbeatResponseRevoked(status="revoked", reason="install_blocked")

    # Check license key status
    if license_key.status in ["revoked", "suspended", "pending"]:
        logger.warning(f"Heartbeat revoked: license {license_key.status} - {request.install_id}")
        await log_heartbeat(db, request.install_id, "revoked", None, payload_hash, source_ip)
        return HeartbeatResponseRevoked(
            status="revoked",
            reason=f"license_{license_key.status}",
        )

    # Check expiry
    if license_key.expires_at and license_key.expires_at < datetime.now(timezone.utc):
        logger.warning(f"Heartbeat revoked: license expired - {request.install_id}")
        await log_heartbeat(db, request.install_id, "revoked", None, payload_hash, source_ip)
        return HeartbeatResponseRevoked(status="revoked", reason="license_expired")

    # C4: Validate fingerprint — mismatch means likely token cache clone
    if install.fingerprint and request.fingerprint != install.fingerprint:
        logger.warning(f"Heartbeat fingerprint mismatch - {request.install_id}")
        await log_heartbeat(db, request.install_id, "fingerprint_mismatch", None, payload_hash, source_ip)
        db.add(AnomalyEvent(
            install_id=request.install_id,
            score=0.9,
            reason="fingerprint_mismatch",
            triggered_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        return HeartbeatResponseRevoked(status="revoked", reason="fingerprint_mismatch")

    # Check domain match (informational — domain change goes through re-activation)
    if install.domain != request.domain:
        logger.warning(
            f"Heartbeat warning: domain mismatch - {install.domain} vs {request.domain}"
        )

    # Check for replay attacks - same payload hash within last 15 min
    replay_window = datetime.now(timezone.utc) - timedelta(minutes=15)
    replay_stmt = select(HeartbeatLog).where(
        HeartbeatLog.install_id == request.install_id,
        HeartbeatLog.payload_hash == payload_hash,
        HeartbeatLog.timestamp > replay_window,
    )
    replay_result = await db.execute(replay_stmt)
    if replay_result.scalar_one_or_none():
        logger.warning(f"Heartbeat rejected: replay attack detected - {request.install_id}")
        await log_heartbeat(db, request.install_id, "replay_detected", None, payload_hash, source_ip)
        return HeartbeatResponseRevoked(status="revoked", reason="replay_attack_detected")

    # Generate new JWT with updated TTL
    private_key = load_private_key()
    now_dt = datetime.now(timezone.utc)
    exp = now_dt + timedelta(seconds=JWT_TTL_SECONDS)

    payload = {
        "iss": JWT_ISSUER,
        "sub": f"install:{request.install_id}",
        "iat": int(now_dt.timestamp()),
        "exp": int(exp.timestamp()),
        "license_key": license_key.key,
        "product": license_key.product.slug,
        "plan": license_key.plan,
        "seats": license_key.seats,
        "features": await fetch_features(db, license_key.product.slug, license_key.plan),
        "domain": install.domain,
        "install_id": request.install_id,
        "revoked": False,
        "server_time": int(now_dt.timestamp()),  # C1: SDK validates local clock against this
    }

    new_token = jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)

    # Generate new shared secret (rotation)
    new_shared_secret_bytes = secrets.token_bytes(32)
    new_shared_secret_b64 = base64.b64encode(new_shared_secret_bytes).decode('ascii')

    # Encrypt and store new shared secret
    from ..crypto import encrypt_secret
    encrypted_secret, nonce_hex = encrypt_secret(request.install_id, new_shared_secret_b64)

    # Update install with last heartbeat time and new shared secret
    stmt = update(Install).where(Install.id == install.id).values(
        last_heartbeat=datetime.now(timezone.utc),
        shared_secret_encrypted=encrypted_secret,
        shared_secret_nonce=nonce_hex,
    )
    await db.execute(stmt)
    await db.commit()

    # Log heartbeat
    await log_heartbeat(db, request.install_id, "valid", None, payload_hash, source_ip)

    logger.info(f"Heartbeat valid: {request.install_id}")

    return HeartbeatResponseValid(
        token=new_token,
        shared_secret=new_shared_secret_b64,
    )


async def log_heartbeat(
    db: AsyncSession,
    install_id: str,
    response_status: str,
    latency_ms: Optional[int],
    payload_hash: Optional[str] = None,
    source_ip: Optional[str] = None,
) -> None:
    """Log heartbeat to database"""
    log_entry = HeartbeatLog(
        install_id=install_id,
        response_status=response_status,
        latency_ms=latency_ms,
        payload_hash=payload_hash,
        source_ip=source_ip,
    )
    db.add(log_entry)
    await db.commit()
