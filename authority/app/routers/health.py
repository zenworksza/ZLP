"""Health check endpoint"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/v1/health")
async def health():
    """Service health check (used by ALB)"""
    return {"ok": True}
