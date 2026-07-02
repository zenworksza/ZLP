"""Revoke install endpoint"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import Install, AuditTrail
from ..database import get_db

router = APIRouter()


@router.post("/revoke/{install_id}")
async def revoke_install(
    install_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Install).where(Install.install_id == install_id)
    result = await db.execute(stmt)
    install = result.scalar_one_or_none()

    if not install:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found"},
        )

    previous_status = install.status
    install.status = "blocked"

    audit = AuditTrail(
        actor="system",
        action="revoke_install",
        target_type="install",
        target_id=install_id,
        timestamp=datetime.now(timezone.utc),
        meta={"previous_status": previous_status},
    )
    db.add(audit)
    await db.commit()

    return {"revoked": True, "install_id": install_id}
