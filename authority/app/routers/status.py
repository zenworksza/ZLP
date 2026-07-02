"""License key status endpoint"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import LicenseKey, Install
from ..database import get_db

router = APIRouter()


@router.get("/status/{license_key}")
async def get_license_status(
    license_key: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LicenseKey)
        .where(LicenseKey.key == license_key)
        .options(selectinload(LicenseKey.installs), selectinload(LicenseKey.product))
    )
    result = await db.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found"},
        )

    installs = [
        {
            "install_id": inst.install_id,
            "domain": inst.domain,
            "status": inst.status,
            "last_heartbeat": inst.last_heartbeat.isoformat() if inst.last_heartbeat else None,
            "first_seen": inst.first_seen.isoformat() if inst.first_seen else None,
        }
        for inst in key.installs
    ]

    return {
        "key": key.key,
        "plan": key.plan,
        "status": key.status,
        "seats": key.seats,
        "customer_ref": key.customer_ref,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "installs": installs,
    }
