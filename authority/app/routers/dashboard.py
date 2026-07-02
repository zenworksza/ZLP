"""Vendor dashboard API routes"""
import os
import secrets
import uuid
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from ..models import Install, LicenseKey, Product, HeartbeatLog, AnomalyEvent, AuditTrail, BillingSubscription, ProductPlan, Invoice
from ..database import get_db
from ..plan_config import get_seeds

_bearer = HTTPBearer()

def _require_dashboard_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    expected = os.environ.get("DASHBOARD_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Dashboard auth not configured")
    if credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Invalid dashboard token")

router = APIRouter(prefix="/dashboard", dependencies=[Depends(_require_dashboard_token)])


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateProductRequest(BaseModel):
    name: str
    slug: str


VALID_RENEWAL_PERIODS = {30, 90, 180}


class CreateKeyRequest(BaseModel):
    product_id: str
    plan: str
    seats: int = 1
    expires_at: Optional[datetime] = None
    customer_ref: Optional[str] = None
    renewal_period_days: Optional[int] = None
    customer_email: Optional[str] = None


class PatchKeyRequest(BaseModel):
    status: Optional[str] = None
    customer_ref: Optional[str] = None
    seats: Optional[int] = None
    expires_at: Optional[datetime] = None
    renewal_period_days: Optional[int] = None
    customer_email: Optional[str] = None


class CreatePlanRequest(BaseModel):
    product_id: str
    slug: str
    display_name: str
    default_seats: int = 1
    max_seats: Optional[int] = None
    features: list[str] = []
    sort_order: int = 0
    price_cents: Optional[int] = None


class PatchPlanRequest(BaseModel):
    display_name: Optional[str] = None
    default_seats: Optional[int] = None
    max_seats: Optional[int] = None
    features: Optional[list[str]] = None
    sort_order: Optional[int] = None
    price_cents: Optional[int] = None


class CreateBillingSubscriptionRequest(BaseModel):
    license_key_id: str
    gateway: str
    gateway_ref: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_invoice_number() -> str:
    now = datetime.now(timezone.utc)
    return f"INV-{now.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"


def _generate_license_key() -> str:
    # 4 segments × 6 chars from base-36 = ~124 bits of entropy (L2)
    chars = string.ascii_uppercase + string.digits
    segments = ["".join(secrets.choice(chars) for _ in range(6)) for _ in range(4)]
    return "ZLP-" + "-".join(segments)


def _audit(actor: str, action: str, target_type: str, target_id: str, meta: Optional[dict] = None) -> AuditTrail:
    return AuditTrail(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        timestamp=datetime.now(timezone.utc),
        meta=meta,
    )


def _format_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _format_key(k: LicenseKey) -> dict:
    return {
        "id": str(k.id),
        "key": k.key,
        "plan": k.plan,
        "seats": k.seats,
        "status": k.status,
        "customer_ref": k.customer_ref,
        "customer_email": k.customer_email,
        "renewal_period_days": k.renewal_period_days,
        "expires_at": _format_dt(k.expires_at),
        "product_slug": k.product.slug if k.product else None,
        "product_name": k.product.name if k.product else None,
        "install_count": len(k.installs) if hasattr(k, "installs") and k.installs is not None else 0,
        "created_at": _format_dt(k.created_at),
    }


def _format_invoice(inv: Invoice) -> dict:
    return {
        "id": str(inv.id),
        "license_key_id": str(inv.license_key_id),
        "invoice_number": inv.invoice_number,
        "period_days": inv.period_days,
        "period_start": _format_dt(inv.period_start),
        "period_end": _format_dt(inv.period_end),
        "amount_cents": inv.amount_cents,
        "currency": inv.currency,
        "status": inv.status,
        "due_date": _format_dt(inv.due_date),
        "sent_at": _format_dt(inv.sent_at),
        "paid_at": _format_dt(inv.paid_at),
        "created_at": _format_dt(inv.created_at),
    }


# ── Plans ────────────────────────────────────────────────────────────────────

def _format_plan(p: ProductPlan) -> dict:
    return {
        "id": str(p.id),
        "product_id": str(p.product_id),
        "slug": p.slug,
        "display_name": p.display_name,
        "default_seats": p.default_seats,
        "max_seats": p.max_seats,
        "features": p.features or [],
        "sort_order": p.sort_order,
        "price_cents": p.price_cents,
        "created_at": _format_dt(p.created_at),
    }


@router.get("/plans")
async def list_plans(
    product_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ProductPlan).order_by(ProductPlan.sort_order)
    if product_id:
        stmt = stmt.where(ProductPlan.product_id == product_id)
    result = await db.execute(stmt)
    return [_format_plan(p) for p in result.scalars().all()]


@router.get("/plans/by-product-slug/{product_slug}")
async def list_plans_by_slug(product_slug: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(ProductPlan)
        .join(Product, ProductPlan.product_id == Product.id)
        .where(Product.slug == product_slug)
        .order_by(ProductPlan.sort_order)
    )
    result = await db.execute(stmt)
    return [_format_plan(p) for p in result.scalars().all()]


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(body: CreatePlanRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(ProductPlan).where(
            ProductPlan.product_id == body.product_id,
            ProductPlan.slug == body.slug,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "plan_slug_exists"})

    plan = ProductPlan(
        product_id=body.product_id,
        slug=body.slug,
        display_name=body.display_name,
        default_seats=body.default_seats,
        max_seats=body.max_seats,
        features=body.features,
        sort_order=body.sort_order,
        price_cents=body.price_cents,
    )
    db.add(plan)
    db.add(_audit("vendor", "create_plan", "product_plan", body.slug, {"product_id": body.product_id}))
    await db.commit()
    await db.refresh(plan)
    return _format_plan(plan)


@router.patch("/plans/{plan_id}")
async def patch_plan(plan_id: str, body: PatchPlanRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProductPlan).where(ProductPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    changes: dict = {}
    if body.display_name is not None:
        plan.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.default_seats is not None:
        plan.default_seats = body.default_seats
        changes["default_seats"] = body.default_seats
    if body.max_seats is not None:
        plan.max_seats = body.max_seats
        changes["max_seats"] = body.max_seats
    if body.features is not None:
        plan.features = body.features
        changes["features"] = body.features
    if body.sort_order is not None:
        plan.sort_order = body.sort_order
        changes["sort_order"] = body.sort_order
    if body.price_cents is not None:
        plan.price_cents = body.price_cents
        changes["price_cents"] = body.price_cents

    db.add(_audit("vendor", "patch_plan", "product_plan", str(plan.id), changes))
    await db.commit()
    await db.refresh(plan)
    return _format_plan(plan)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_200_OK)
async def delete_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProductPlan).where(ProductPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    db.add(_audit("vendor", "delete_plan", "product_plan", str(plan.id), {"slug": plan.slug}))
    await db.delete(plan)
    await db.commit()
    return {"deleted": True, "id": plan_id}


@router.post("/plans/seed/{product_slug}", status_code=status.HTTP_201_CREATED)
async def seed_plans(product_slug: str, db: AsyncSession = Depends(get_db)):
    product_result = await db.execute(select(Product).where(Product.slug == product_slug))
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "product_not_found"})

    seeds = get_seeds(product_slug)
    created = []
    for seed in seeds:
        exists = await db.execute(
            select(ProductPlan).where(ProductPlan.product_id == product.id, ProductPlan.slug == seed.slug)
        )
        if exists.scalar_one_or_none():
            continue
        plan = ProductPlan(
            product_id=product.id,
            slug=seed.slug,
            display_name=seed.display_name,
            default_seats=seed.default_seats,
            max_seats=seed.max_seats,
            features=seed.features,
            sort_order=seed.sort_order,
        )
        db.add(plan)
        created.append(seed.slug)

    if created:
        db.add(_audit("vendor", "seed_plans", "product", product_slug, {"created": created}))
        await db.commit()

    return {"seeded": created, "product_slug": product_slug}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    total_installs_result = await db.execute(select(func.count()).select_from(Install))
    total_installs = total_installs_result.scalar() or 0

    active_result = await db.execute(select(func.count()).select_from(Install).where(Install.status == "active"))
    active = active_result.scalar() or 0

    blocked_result = await db.execute(select(func.count()).select_from(Install).where(Install.status == "blocked"))
    blocked = blocked_result.scalar() or 0

    anomalous_result = await db.execute(select(func.count()).select_from(Install).where(Install.status == "anomalous"))
    anomalous = anomalous_result.scalar() or 0

    total_keys_result = await db.execute(select(func.count()).select_from(LicenseKey))
    total_keys = total_keys_result.scalar() or 0

    unresolved_result = await db.execute(
        select(func.count()).select_from(AnomalyEvent).where(AnomalyEvent.resolved_at.is_(None))
    )
    unresolved_alerts = unresolved_result.scalar() or 0

    return {
        "total_installs": total_installs,
        "active": active,
        "blocked": blocked,
        "anomalous": anomalous,
        "total_keys": total_keys,
        "unresolved_alerts": unresolved_alerts,
    }


# ── Products ──────────────────────────────────────────────────────────────────

@router.get("/products")
async def list_products(db: AsyncSession = Depends(get_db)):
    stmt = select(Product).options(selectinload(Product.license_keys))
    result = await db.execute(stmt)
    products = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "slug": p.slug,
            "created_at": _format_dt(p.created_at),
            "key_count": len(p.license_keys),
        }
        for p in products
    ]


@router.delete("/products/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(product_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).options(selectinload(Product.license_keys)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    if product.license_keys:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "product_has_keys", "key_count": len(product.license_keys)},
        )
    db.add(_audit("vendor", "delete_product", "product", product.slug))
    await db.delete(product)
    await db.commit()
    return {"deleted": True, "id": product_id}


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(body: CreateProductRequest, db: AsyncSession = Depends(get_db)):
    product = Product(name=body.name, slug=body.slug)
    db.add(product)
    db.add(_audit("vendor", "create_product", "product", body.slug))
    await db.commit()
    await db.refresh(product)

    return {
        "id": str(product.id),
        "name": product.name,
        "slug": product.slug,
        "created_at": _format_dt(product.created_at),
        "key_count": 0,
    }


# ── License keys ──────────────────────────────────────────────────────────────

@router.get("/keys")
async def list_keys(
    product_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LicenseKey)
        .options(selectinload(LicenseKey.product), selectinload(LicenseKey.installs))
    )
    if product_id:
        stmt = stmt.where(LicenseKey.product_id == product_id)
    result = await db.execute(stmt)
    keys = result.scalars().all()

    return [_format_key(k) for k in keys]


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_key(body: CreateKeyRequest, db: AsyncSession = Depends(get_db)):
    product_result = await db.execute(select(Product).where(Product.id == body.product_id))
    product = product_result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    if body.renewal_period_days is not None and body.renewal_period_days not in VALID_RENEWAL_PERIODS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": "invalid_renewal_period", "valid": list(VALID_RENEWAL_PERIODS)})

    now = datetime.now(timezone.utc)
    expires_at = body.expires_at
    if expires_at is None and body.renewal_period_days:
        expires_at = now + timedelta(days=body.renewal_period_days)

    key_str = _generate_license_key()
    key = LicenseKey(
        product_id=body.product_id,
        key=key_str,
        plan=body.plan,
        seats=body.seats,
        expires_at=expires_at,
        customer_ref=body.customer_ref,
        renewal_period_days=body.renewal_period_days,
        customer_email=body.customer_email,
        status="pending",  # awaiting first payment — not active until invoice paid
    )
    db.add(key)
    db.add(_audit("vendor", "create_key", "license_key", key_str, {
        "plan": body.plan, "seats": body.seats,
        "renewal_period_days": body.renewal_period_days, "status": "pending",
    }))
    await db.commit()
    await db.refresh(key)

    # Generate first-period invoice immediately and email it — key is NOT sent until paid
    if body.renewal_period_days and expires_at:
        plan_result = await db.execute(
            select(ProductPlan)
            .join(Product, ProductPlan.product_id == Product.id)
            .where(Product.id == key.product_id, ProductPlan.slug == key.plan)
        )
        plan_row = plan_result.scalar_one_or_none()
        price_per_30 = plan_row.price_cents if plan_row and plan_row.price_cents else 0
        amount_cents = int(price_per_30 * (body.renewal_period_days / 30))

        invoice = Invoice(
            license_key_id=key.id,
            invoice_number=_next_invoice_number(),
            period_days=body.renewal_period_days,
            period_start=now,
            period_end=expires_at,
            amount_cents=amount_cents,
            currency=os.getenv("DEFAULT_CURRENCY", "ZAR"),
            status="pending",
            due_date=now + timedelta(days=7),
        )
        db.add(invoice)
        await db.flush()

        if body.customer_email:
            from ..services.email import send_invoice_email
            sent = send_invoice_email(
                to_email=body.customer_email,
                invoice_number=invoice.invoice_number,
                license_key=key_str,
                product_name=product.name,
                plan_name=body.plan.capitalize(),
                period_days=body.renewal_period_days,
                period_start=now,
                period_end=expires_at,
                amount_cents=amount_cents,
                currency=invoice.currency,
                due_date=invoice.due_date,
            )
            if sent:
                invoice.status = "sent"
                invoice.sent_at = now

        await db.commit()

    await db.refresh(key, ["product", "installs"])
    return _format_key(key)


@router.patch("/keys/{key_id}")
async def patch_key(key_id: str, body: PatchKeyRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LicenseKey).where(LicenseKey.id == key_id).options(selectinload(LicenseKey.product), selectinload(LicenseKey.installs))
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    changes: dict = {}
    if body.status is not None:
        changes["status"] = body.status
        key.status = body.status
    if body.customer_ref is not None:
        changes["customer_ref"] = body.customer_ref
        key.customer_ref = body.customer_ref
    if body.seats is not None:
        changes["seats"] = body.seats
        key.seats = body.seats
    if body.expires_at is not None:
        changes["expires_at"] = body.expires_at.isoformat()
        key.expires_at = body.expires_at
    if body.renewal_period_days is not None:
        if body.renewal_period_days not in VALID_RENEWAL_PERIODS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": "invalid_renewal_period"})
        changes["renewal_period_days"] = body.renewal_period_days
        key.renewal_period_days = body.renewal_period_days
    if body.customer_email is not None:
        changes["customer_email"] = body.customer_email
        key.customer_email = body.customer_email

    db.add(_audit("vendor", "patch_key", "license_key", str(key.id), changes))
    await db.commit()
    await db.refresh(key, ["product", "installs"])
    return _format_key(key)


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LicenseKey).where(LicenseKey.id == key_id).options(selectinload(LicenseKey.installs))
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    key.status = "revoked"
    for install in key.installs:
        install.status = "blocked"

    db.add(_audit("vendor", "revoke_key", "license_key", str(key.id), {"install_count": len(key.installs)}))
    await db.commit()

    return {"revoked": True, "key_id": key_id, "installs_blocked": len(key.installs)}


# ── Installs ──────────────────────────────────────────────────────────────────

@router.get("/installs")
async def list_installs(
    key_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Install)
    if key_id:
        stmt = stmt.where(Install.key_id == key_id)
    if status:
        stmt = stmt.where(Install.status == status)

    result = await db.execute(stmt)
    installs = result.scalars().all()

    # Fetch max anomaly score per install (unresolved)
    install_ids = [i.install_id for i in installs]
    anomaly_scores: dict[str, float] = {}
    if install_ids:
        score_stmt = (
            select(AnomalyEvent.install_id, func.max(AnomalyEvent.score).label("max_score"))
            .where(
                AnomalyEvent.install_id.in_(install_ids),
                AnomalyEvent.resolved_at.is_(None),
            )
            .group_by(AnomalyEvent.install_id)
        )
        score_result = await db.execute(score_stmt)
        for row in score_result:
            anomaly_scores[row.install_id] = row.max_score

    return [
        {
            "install_id": i.install_id,
            "domain": i.domain,
            "status": i.status,
            "last_heartbeat": _format_dt(i.last_heartbeat),
            "first_seen": _format_dt(i.first_seen),
            "anomaly_score": anomaly_scores.get(i.install_id),
        }
        for i in installs
    ]


@router.get("/installs/{install_id}")
async def get_install(install_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Install)
        .where(Install.install_id == install_id)
        .options(selectinload(Install.license_key).selectinload(LicenseKey.product))
    )
    result = await db.execute(stmt)
    install = result.scalar_one_or_none()

    if not install:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    key = install.license_key
    product = key.product if key else None

    return {
        "install_id": install.install_id,
        "domain": install.domain,
        "status": install.status,
        "last_heartbeat": _format_dt(install.last_heartbeat),
        "first_seen": _format_dt(install.first_seen),
        "license_key": key.key if key else None,
        "product": product.slug if product else None,
        "plan": key.plan if key else None,
        "machine_id": install.machine_id,
    }


@router.post("/installs/{install_id}/block")
async def block_install(install_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Install).where(Install.install_id == install_id))
    install = result.scalar_one_or_none()

    if not install:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    install.status = "blocked"
    db.add(_audit("vendor", "block_install", "install", install_id))
    await db.commit()

    return {"blocked": True, "install_id": install_id}


@router.get("/installs/{install_id}/heartbeats")
async def get_heartbeats(
    install_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(HeartbeatLog)
        .where(HeartbeatLog.install_id == install_id)
        .order_by(HeartbeatLog.timestamp.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "install_id": log.install_id,
            "timestamp": _format_dt(log.timestamp),
            "latency_ms": log.latency_ms,
            "payload_hash": log.payload_hash,
            "response_status": log.response_status,
        }
        for log in logs
    ]


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.get("/invoices")
async def list_invoices(
    key_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.license_key).selectinload(LicenseKey.product))
        .order_by(Invoice.created_at.desc())
    )
    if key_id:
        stmt = stmt.where(Invoice.license_key_id == key_id)
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    return [
        {
            **_format_invoice(inv),
            "license_key": inv.license_key.key if inv.license_key else None,
            "customer_email": inv.license_key.customer_email if inv.license_key else None,
            "product_name": inv.license_key.product.name if inv.license_key and inv.license_key.product else None,
            "plan": inv.license_key.plan if inv.license_key else None,
        }
        for inv in invoices
    ]


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_invoice_paid(invoice_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.license_key))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    if invoice.status == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "already_paid"})
    if invoice.status == "void":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "invoice_void"})

    now = datetime.now(timezone.utc)
    invoice.status = "paid"
    invoice.paid_at = now

    key = invoice.license_key
    is_first_payment = key and key.status == "pending"

    if key:
        if is_first_payment:
            # First payment: activate the key; expires_at was already set at creation
            key.status = "active"
        else:
            # Renewal: extend from current expiry (or now if already lapsed)
            base = key.expires_at if key.expires_at and key.expires_at > now else now
            key.expires_at = base + timedelta(days=invoice.period_days)
            if key.status == "suspended":
                key.status = "active"

        db.add(_audit("vendor", "invoice.mark_paid", "license_key", key.key, {
            "invoice_number": invoice.invoice_number,
            "first_payment": is_first_payment,
            "new_expires_at": key.expires_at.isoformat() if key.expires_at else None,
        }))

    await db.commit()
    await db.refresh(invoice)

    if key and key.customer_email:
        product_result = await db.execute(select(Product).where(Product.id == key.product_id))
        product = product_result.scalar_one_or_none()
        product_name = product.name if product else key.plan

        if is_first_payment:
            # First payment: now safe to deliver the key
            from ..services.email import send_key_provisioning_email
            send_key_provisioning_email(
                to_email=key.customer_email,
                license_key=key.key,
                product_name=product_name,
                plan_name=key.plan.capitalize(),
                seats=key.seats,
                expires_at=key.expires_at,
                renewal_period_days=key.renewal_period_days,
            )
        else:
            # Renewal: confirm payment and new expiry
            from ..services.email import send_renewal_confirmation_email
            send_renewal_confirmation_email(
                to_email=key.customer_email,
                invoice_number=invoice.invoice_number,
                license_key=key.key,
                product_name=product_name,
                plan_name=key.plan.capitalize(),
                new_expires_at=key.expires_at,
                amount_cents=invoice.amount_cents,
                currency=invoice.currency,
            )

    return {**_format_invoice(invoice), "new_expires_at": _format_dt(key.expires_at) if key else None}


@router.post("/invoices/{invoice_id}/resend")
async def resend_invoice(invoice_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.license_key).selectinload(LicenseKey.product))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    key = invoice.license_key
    if not key or not key.customer_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": "no_customer_email"})

    from ..services.email import send_invoice_email
    sent = send_invoice_email(
        to_email=key.customer_email,
        invoice_number=invoice.invoice_number,
        license_key=key.key,
        product_name=key.product.name if key.product else key.plan,
        plan_name=key.plan.capitalize(),
        period_days=invoice.period_days,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        amount_cents=invoice.amount_cents,
        currency=invoice.currency,
        due_date=invoice.due_date,
    )
    if sent:
        invoice.status = "sent"
        invoice.sent_at = datetime.now(timezone.utc)
        db.add(_audit("vendor", "invoice.resend", "invoice", str(invoice.id), {"to": key.customer_email}))
        await db.commit()
        await db.refresh(invoice)

    return {**_format_invoice(invoice), "emailed": sent}


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(invoice_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})
    if invoice.status == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "cannot_void_paid"})
    invoice.status = "void"
    db.add(_audit("vendor", "invoice.void", "invoice", str(invoice.id), {}))
    await db.commit()
    return _format_invoice(invoice)


# ── Anomalies ─────────────────────────────────────────────────────────────────

@router.get("/anomalies")
async def list_anomalies(
    resolved: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AnomalyEvent)
    if not resolved:
        stmt = stmt.where(AnomalyEvent.resolved_at.is_(None))
    stmt = stmt.order_by(AnomalyEvent.triggered_at.desc())
    result = await db.execute(stmt)
    events = result.scalars().all()

    # Fetch domain for each install_id
    install_ids = list({e.install_id for e in events})
    domains: dict[str, str] = {}
    if install_ids:
        domain_result = await db.execute(
            select(Install.install_id, Install.domain).where(Install.install_id.in_(install_ids))
        )
        for row in domain_result:
            domains[row.install_id] = row.domain

    return [
        {
            "id": str(e.id),
            "install_id": e.install_id,
            "domain": domains.get(e.install_id),
            "score": e.score,
            "reason": e.reason,
            "triggered_at": _format_dt(e.triggered_at),
            "resolved_at": _format_dt(e.resolved_at),
        }
        for e in events
    ]


@router.post("/anomalies/{anomaly_id}/resolve")
async def resolve_anomaly(anomaly_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnomalyEvent).where(AnomalyEvent.id == anomaly_id))
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    event.resolved_at = datetime.now(timezone.utc)
    db.add(_audit("vendor", "resolve_anomaly", "anomaly_event", anomaly_id))
    await db.commit()

    return {"resolved": True, "anomaly_id": anomaly_id}


# ── Audit log ─────────────────────────────────────────────────────────────────

# ── Billing subscriptions ─────────────────────────────────────────────────────

@router.get("/billing/subscriptions")
async def list_billing_subscriptions(db: AsyncSession = Depends(get_db)):
    stmt = select(BillingSubscription).options(selectinload(BillingSubscription.license_key))
    result = await db.execute(stmt)
    subs = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "license_key_id": str(s.license_key_id),
            "license_key": s.license_key.key if s.license_key else None,
            "gateway": s.gateway,
            "gateway_ref": s.gateway_ref,
            "status": s.status,
            "overdue_since": _format_dt(s.overdue_since),
            "last_payment_at": _format_dt(s.last_payment_at),
            "created_at": _format_dt(s.created_at),
        }
        for s in subs
    ]


@router.post("/billing/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_billing_subscription(body: CreateBillingSubscriptionRequest, db: AsyncSession = Depends(get_db)):
    key_result = await db.execute(select(LicenseKey).where(LicenseKey.id == body.license_key_id))
    key = key_result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    sub = BillingSubscription(
        license_key_id=body.license_key_id,
        gateway=body.gateway,
        gateway_ref=body.gateway_ref,
    )
    db.add(sub)
    db.add(_audit("vendor", "billing.subscription_linked", "license_key", key.key, {"gateway": body.gateway, "gateway_ref": body.gateway_ref}))
    await db.commit()
    await db.refresh(sub)

    return {
        "id": str(sub.id),
        "license_key_id": str(sub.license_key_id),
        "license_key": key.key,
        "gateway": sub.gateway,
        "gateway_ref": sub.gateway_ref,
        "status": sub.status,
        "overdue_since": _format_dt(sub.overdue_since),
        "last_payment_at": _format_dt(sub.last_payment_at),
        "created_at": _format_dt(sub.created_at),
    }


@router.delete("/billing/subscriptions/{sub_id}", status_code=status.HTTP_200_OK)
async def delete_billing_subscription(sub_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BillingSubscription).where(BillingSubscription.id == sub_id).options(selectinload(BillingSubscription.license_key))
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"})

    key_ref = sub.license_key.key if sub.license_key else str(sub.license_key_id)
    db.add(_audit("vendor", "billing.subscription_unlinked", "license_key", key_ref, {"gateway": sub.gateway, "gateway_ref": sub.gateway_ref}))
    await db.delete(sub)
    await db.commit()

    return {"deleted": True, "id": sub_id}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditTrail)
        .order_by(AuditTrail.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "actor": e.actor,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "timestamp": _format_dt(e.timestamp),
            "meta": e.meta,
        }
        for e in entries
    ]
