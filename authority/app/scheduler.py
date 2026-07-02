"""APScheduler integration for background jobs"""
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

from .database import async_session_maker
from .models import AuditTrail, BillingSubscription, Install, HeartbeatLog, AnomalyEvent, LicenseKey, Invoice, ProductPlan, Product

scheduler = AsyncIOScheduler()


async def check_heartbeat_expiry():
    threshold = datetime.now(timezone.utc) - timedelta(minutes=35)
    async with async_session_maker() as db:
        from sqlalchemy import select
        stmt = select(Install).where(
            Install.status == "active",
            Install.last_heartbeat.isnot(None),
            Install.last_heartbeat < threshold,
        )
        result = await db.execute(stmt)
        stale = result.scalars().all()

        for install in stale:
            existing_stmt = select(AnomalyEvent).where(
                AnomalyEvent.install_id == install.install_id,
                AnomalyEvent.reason == "heartbeat_missed",
                AnomalyEvent.resolved_at.is_(None),
            )
            existing_result = await db.execute(existing_stmt)
            already_flagged = existing_result.scalar_one_or_none()

            if not already_flagged:
                event = AnomalyEvent(
                    install_id=install.install_id,
                    score=0.5,
                    reason="heartbeat_missed",
                    triggered_at=datetime.now(timezone.utc),
                )
                db.add(event)

        await db.commit()


async def score_anomalies():
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    async with async_session_maker() as db:
        from sqlalchemy import select, func
        installs_result = await db.execute(
            select(Install).where(Install.status == "active")
        )
        installs = installs_result.scalars().all()

        for install in installs:
            logs_result = await db.execute(
                select(HeartbeatLog).where(
                    HeartbeatLog.install_id == install.install_id,
                    HeartbeatLog.timestamp >= window_start,
                )
            )
            logs = logs_result.scalars().all()

            if not logs:
                continue

            total = len(logs)
            fp_mismatches = sum(1 for l in logs if l.response_status == "fingerprint_mismatch")
            replay_attempts = sum(1 for l in logs if l.response_status == "replay_detected")
            error_count = sum(1 for l in logs if l.response_status == "error")
            error_rate = error_count / total if total > 0 else 0.0

            score = round(
                min(fp_mismatches / 2, 1.0) * 0.50
                + min(replay_attempts / 2, 1.0) * 0.30
                + min(error_rate, 1.0) * 0.20,
                4,
            )

            if score <= 0.6:
                continue

            recent_event_result = await db.execute(
                select(AnomalyEvent).where(
                    AnomalyEvent.install_id == install.install_id,
                    AnomalyEvent.resolved_at.is_(None),
                    AnomalyEvent.triggered_at >= one_hour_ago,
                )
            )
            recent_event = recent_event_result.scalar_one_or_none()

            if recent_event:
                continue

            reason_parts = []
            if fp_mismatches:
                reason_parts.append(f"fingerprint_mismatch:{fp_mismatches}")
            if replay_attempts:
                reason_parts.append(f"replay_detected:{replay_attempts}")
            if error_rate > 0:
                reason_parts.append(f"error_rate:{error_rate:.2f}")
            reason = ",".join(reason_parts) or "anomalous_pattern"

            event = AnomalyEvent(
                install_id=install.install_id,
                score=score,
                reason=reason,
                triggered_at=datetime.now(timezone.utc),
            )
            db.add(event)

            if score > 0.85:
                install.status = "anomalous"

        await db.commit()


async def enforce_billing_grace_period():
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    async with async_session_maker() as db:
        from sqlalchemy import select
        stmt = select(BillingSubscription).where(
            BillingSubscription.status == "overdue",
            BillingSubscription.overdue_since.isnot(None),
            BillingSubscription.overdue_since < threshold,
        )
        result = await db.execute(stmt)
        overdue_subs = result.scalars().all()

        for sub in overdue_subs:
            sub.status = "suspended"

            key_result = await db.execute(
                select(LicenseKey).where(LicenseKey.id == sub.license_key_id)
            )
            key = key_result.scalar_one_or_none()
            if key:
                key.status = "suspended"

            db.add(AuditTrail(
                actor="system",
                action="billing.auto_suspended",
                target_type="license_key",
                target_id=key.key if key else str(sub.license_key_id),
                timestamp=datetime.now(timezone.utc),
                meta={"gateway": sub.gateway, "gateway_ref": sub.gateway_ref, "overdue_since": sub.overdue_since.isoformat()},
            ))

        await db.commit()


async def suspend_overdue_keys():
    """
    Runs every few hours. Suspend active keys that:
    - have renewal billing enabled (renewal_period_days set)
    - have passed their expiry date
    - have at least one outstanding (unpaid) invoice
    On next heartbeat the agent will receive status=revoked and hard-block the install.
    """
    now = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        from sqlalchemy import select, exists as sa_exists

        overdue_invoice_exists = (
            select(Invoice.id)
            .where(
                Invoice.license_key_id == LicenseKey.id,
                Invoice.status.in_(["pending", "sent"]),
            )
            .correlate(LicenseKey)
            .exists()
        )

        stmt = select(LicenseKey).where(
            LicenseKey.renewal_period_days.isnot(None),
            LicenseKey.expires_at.isnot(None),
            LicenseKey.expires_at < now,
            LicenseKey.status == "active",
            overdue_invoice_exists,
        )
        result = await db.execute(stmt)
        keys = result.scalars().all()

        for key in keys:
            key.status = "suspended"
            db.add(AuditTrail(
                actor="system",
                action="billing.auto_suspended",
                target_type="license_key",
                target_id=key.key,
                timestamp=now,
                meta={"reason": "invoice_overdue", "expired_at": key.expires_at.isoformat()},
            ))

        if keys:
            await db.commit()
            logger.info("Auto-suspended %d overdue keys", len(keys))


def _next_invoice_number() -> str:
    now = datetime.now(timezone.utc)
    return f"INV-{now.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"


async def generate_renewal_invoices():
    """
    Daily job. Find keys with renewal_period_days set that expire within 14 days.
    Generate an invoice for each if one doesn't already exist for this renewal window,
    then email it to the customer.
    """
    now = datetime.now(timezone.utc)
    lookahead = now + timedelta(days=14)

    async with async_session_maker() as db:
        from sqlalchemy import select, and_, or_

        stmt = (
            select(LicenseKey)
            .join(Product, LicenseKey.product_id == Product.id)
            .where(
                LicenseKey.renewal_period_days.isnot(None),
                LicenseKey.expires_at.isnot(None),
                LicenseKey.expires_at > now,
                LicenseKey.expires_at <= lookahead,
                LicenseKey.status == "active",
            )
        )
        result = await db.execute(stmt)
        expiring_keys = result.scalars().all()

        for key in expiring_keys:
            # Skip if an open invoice already covers this renewal window
            existing = await db.execute(
                select(Invoice).where(
                    Invoice.license_key_id == key.id,
                    Invoice.period_end == key.expires_at,
                    Invoice.status.in_(["pending", "sent"]),
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Derive price from plan config
            plan_result = await db.execute(
                select(ProductPlan)
                .join(Product, ProductPlan.product_id == Product.id)
                .where(Product.id == key.product_id, ProductPlan.slug == key.plan)
            )
            plan = plan_result.scalar_one_or_none()
            price_per_30 = plan.price_cents if plan and plan.price_cents else 0
            period_days = key.renewal_period_days
            amount_cents = int(price_per_30 * (period_days / 30))

            period_start = key.expires_at
            period_end = key.expires_at + timedelta(days=period_days)
            due_date = key.expires_at - timedelta(days=7)

            invoice = Invoice(
                license_key_id=key.id,
                invoice_number=_next_invoice_number(),
                period_days=period_days,
                period_start=period_start,
                period_end=period_end,
                amount_cents=amount_cents,
                currency=os.getenv("DEFAULT_CURRENCY", "ZAR"),
                status="pending",
                due_date=due_date,
            )
            db.add(invoice)
            await db.flush()  # get invoice.id assigned

            db.add(AuditTrail(
                actor="system",
                action="invoice.generated",
                target_type="license_key",
                target_id=key.key,
                timestamp=now,
                meta={"invoice_number": invoice.invoice_number, "amount_cents": amount_cents, "period_days": period_days},
            ))

            # Send email if customer_email is set
            if key.customer_email:
                product_result = await db.execute(select(Product).where(Product.id == key.product_id))
                product = product_result.scalar_one_or_none()
                from .services.email import send_invoice_email
                sent = send_invoice_email(
                    to_email=key.customer_email,
                    invoice_number=invoice.invoice_number,
                    license_key=key.key,
                    product_name=product.name if product else key.plan,
                    plan_name=key.plan.capitalize(),
                    period_days=period_days,
                    period_start=period_start,
                    period_end=period_end,
                    amount_cents=amount_cents,
                    currency=invoice.currency,
                    due_date=due_date,
                )
                if sent:
                    invoice.status = "sent"
                    invoice.sent_at = now

        await db.commit()


def start_scheduler():
    scheduler.add_job(check_heartbeat_expiry, "interval", minutes=5, id="heartbeat_expiry")
    scheduler.add_job(score_anomalies, "interval", minutes=15, id="anomaly_scorer")
    scheduler.add_job(enforce_billing_grace_period, "interval", minutes=5, id="billing_grace")
    scheduler.add_job(generate_renewal_invoices, "cron", hour=8, minute=0, id="renewal_invoices")
    scheduler.add_job(suspend_overdue_keys, "interval", hours=4, id="suspend_overdue")
    scheduler.start()


def stop_scheduler():
    scheduler.shutdown()
