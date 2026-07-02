"""Billing gateway webhook handlers — PayFast ITN and PayPal"""
import hashlib
import hmac
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..database import async_session_maker
from ..models import AuditTrail, BillingSubscription, LicenseKey

logger = logging.getLogger(__name__)

PAYFAST_MERCHANT_ID  = os.getenv("PAYFAST_MERCHANT_ID", "")
PAYFAST_MERCHANT_KEY = os.getenv("PAYFAST_MERCHANT_KEY", "")
PAYFAST_PASSPHRASE   = os.getenv("PAYFAST_PASSPHRASE", "")
PAYFAST_SANDBOX      = os.getenv("PAYFAST_SANDBOX", "false").lower() == "true"

PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID    = os.getenv("PAYPAL_WEBHOOK_ID", "")
PAYPAL_SANDBOX       = os.getenv("PAYPAL_SANDBOX", "false").lower() == "true"

router = APIRouter()


def _payfast_validate_url() -> str:
    if PAYFAST_SANDBOX:
        return "https://sandbox.payfast.co.za/eng/query/validate"
    return "https://www.payfast.co.za/eng/query/validate"


def _paypal_base_url() -> str:
    if PAYPAL_SANDBOX:
        return "https://api-m.sandbox.paypal.com"
    return "https://api-m.paypal.com"


def _build_payfast_signature_string(post_data: dict) -> str:
    pairs = []
    for key, value in post_data.items():
        if key == "signature":
            continue
        if value == "" or value is None:
            continue
        pairs.append(f"{key}={urllib.parse.quote_plus(str(value))}")
    sig_string = "&".join(pairs)
    if PAYFAST_PASSPHRASE:
        sig_string += f"&passphrase={urllib.parse.quote_plus(PAYFAST_PASSPHRASE)}"
    return sig_string


async def _verify_payfast_itn(post_data: dict) -> bool:
    sig_string = _build_payfast_signature_string(post_data)
    expected_sig = hashlib.md5(sig_string.encode("utf-8")).hexdigest()
    received_sig = post_data.get("signature", "")

    if not hmac.compare_digest(expected_sig, received_sig):
        logger.warning("PayFast ITN signature mismatch")
        return False

    validate_data = {k: v for k, v in post_data.items() if k != "signature"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _payfast_validate_url(),
                data=validate_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.text.strip() != "VALID":
            logger.warning("PayFast server validation returned: %s", resp.text.strip())
            return False
    except Exception as exc:
        logger.warning("PayFast server validation request failed: %s", exc)
        return False

    return True


async def _get_paypal_oauth_token(client: httpx.AsyncClient) -> Optional[str]:
    try:
        resp = await client.post(
            f"{_paypal_base_url()}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as exc:
        logger.warning("PayPal OAuth token request failed: %s", exc)
        return None


async def _verify_paypal_webhook(request: Request, event: dict) -> bool:
    async with httpx.AsyncClient(timeout=10.0) as client:
        token = await _get_paypal_oauth_token(client)
        if not token:
            return False

        verify_payload = {
            "auth_algo": request.headers.get("paypal-auth-algo", ""),
            "cert_url": request.headers.get("paypal-cert-url", ""),
            "transmission_id": request.headers.get("paypal-transmission-id", ""),
            "transmission_sig": request.headers.get("paypal-transmission-sig", ""),
            "transmission_time": request.headers.get("paypal-transmission-time", ""),
            "webhook_id": PAYPAL_WEBHOOK_ID,
            "webhook_event": event,
        }

        try:
            resp = await client.post(
                f"{_paypal_base_url()}/v1/notifications/verify-webhook-signature",
                json=verify_payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            verification_status = resp.json().get("verification_status", "")
            if verification_status != "SUCCESS":
                logger.warning("PayPal webhook verification returned: %s", verification_status)
                return False
        except Exception as exc:
            logger.warning("PayPal webhook verification request failed: %s", exc)
            return False

    return True


async def handle_payment_success(sub: BillingSubscription, db) -> None:
    now = datetime.now(timezone.utc)
    sub.overdue_since = None
    sub.status = "active"
    sub.last_payment_at = now

    result = await db.execute(
        select(LicenseKey).where(LicenseKey.id == sub.license_key_id)
    )
    key = result.scalar_one_or_none()
    if key and key.status == "suspended":
        key.status = "active"

    db.add(AuditTrail(
        actor="system",
        action="billing.payment_success",
        target_type="license_key",
        target_id=key.key if key else str(sub.license_key_id),
        timestamp=now,
        meta={"gateway": sub.gateway, "gateway_ref": sub.gateway_ref},
    ))


async def handle_payment_failure(sub: BillingSubscription, db) -> None:
    now = datetime.now(timezone.utc)
    if sub.overdue_since is None:
        sub.overdue_since = now
    sub.status = "overdue"

    result = await db.execute(
        select(LicenseKey).where(LicenseKey.id == sub.license_key_id)
    )
    key = result.scalar_one_or_none()

    db.add(AuditTrail(
        actor="system",
        action="billing.payment_failed",
        target_type="license_key",
        target_id=key.key if key else str(sub.license_key_id),
        timestamp=now,
        meta={"gateway": sub.gateway, "gateway_ref": sub.gateway_ref},
    ))


@router.post("/billing/payfast/webhook")
async def payfast_webhook(request: Request):
    form = await request.form()
    post_data = dict(form)

    if not PAYFAST_MERCHANT_ID:
        return JSONResponse({"ok": True})

    verified = await _verify_payfast_itn(post_data)
    if not verified:
        return JSONResponse({"ok": True})

    gateway_ref = post_data.get("m_payment_id", "")
    if not gateway_ref:
        logger.warning("PayFast ITN missing m_payment_id")
        return JSONResponse({"ok": True})

    async with async_session_maker() as db:
        result = await db.execute(
            select(BillingSubscription).where(BillingSubscription.gateway_ref == gateway_ref)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            logger.warning("PayFast ITN: no subscription found for gateway_ref=%s", gateway_ref)
            return JSONResponse({"ok": True})

        payment_status = post_data.get("payment_status", "")
        if payment_status == "COMPLETE":
            await handle_payment_success(sub, db)
        elif payment_status in ("FAILED", "CANCELLED"):
            await handle_payment_failure(sub, db)
        else:
            logger.warning("PayFast ITN: unhandled payment_status=%s", payment_status)
            return JSONResponse({"ok": True})

        await db.commit()

    return JSONResponse({"ok": True})


@router.post("/billing/paypal/webhook")
async def paypal_webhook(request: Request):
    if not PAYPAL_CLIENT_ID:
        return JSONResponse({"ok": True})

    try:
        event = await request.json()
    except Exception:
        logger.warning("PayPal webhook: invalid JSON body")
        return JSONResponse({"ok": True})

    verified = await _verify_paypal_webhook(request, event)
    if not verified:
        return JSONResponse({"ok": True})

    event_type = event.get("event_type", "")
    purchase_units = event.get("resource", {}).get("purchase_units", [])
    gateway_ref = ""
    if purchase_units:
        gateway_ref = purchase_units[0].get("custom_id") or purchase_units[0].get("reference_id", "")

    if not gateway_ref:
        logger.warning("PayPal webhook: could not extract gateway_ref for event_type=%s", event_type)
        return JSONResponse({"ok": True})

    async with async_session_maker() as db:
        result = await db.execute(
            select(BillingSubscription).where(BillingSubscription.gateway_ref == gateway_ref)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            logger.warning("PayPal webhook: no subscription found for gateway_ref=%s", gateway_ref)
            return JSONResponse({"ok": True})

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            await handle_payment_success(sub, db)
        elif event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED", "BILLING.SUBSCRIPTION.CANCELLED"):
            await handle_payment_failure(sub, db)
        else:
            return JSONResponse({"ok": True})

        await db.commit()

    return JSONResponse({"ok": True})
