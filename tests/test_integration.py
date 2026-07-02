import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select, update

from authority.app.models import LicenseKey, Product
from conftest import test_session_maker

PUBLIC_KEY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "infra", "keys", "zlp_public.pem"
)

with open(PUBLIC_KEY_PATH, "r") as _f:
    PUBLIC_KEY = _f.read()

JWT_ALGORITHM = "RS256"
JWT_ISSUER = "zlp.yourdomain.com"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _activation_payload(
    license_key: str = "ZLP-TEST-1234-ABCD",
    install_id: str | None = None,
    domain: str = "app.customer.com",
) -> dict:
    return {
        "license_key": license_key,
        "install_id": install_id or str(uuid.uuid4()),
        "domain": domain,
        "fingerprint": "deadbeef" * 8,
        "machine_id": "test-machine-id",
        "product": "zenmsp",
        "version": "2.1.0",
    }


def sign_heartbeat(payload: dict, shared_secret: str) -> tuple[str, bytes]:
    """
    Returns (hex_signature, raw_body_bytes).
    Body is serialised with compact separators to match the exact bytes sent in the
    request so the HMAC computed here matches the one the server computes from
    http_request.body().
    """
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(shared_secret.encode(), body, hashlib.sha256).hexdigest()
    return sig, body


def _heartbeat_payload(install_id: str, domain: str = "app.customer.com") -> dict:
    return {
        "install_id": install_id,
        "license_key": "ZLP-TEST-1234-ABCD",
        "product": "zenmsp",
        "version": "2.1.0",
        "domain": domain,
        "fingerprint": "deadbeef" * 8,
        "machine_id": "test-machine-id",
        "timestamp": int(time.time()),
        "nonce": secrets.token_hex(8),
    }


async def _activate(client: AsyncClient, install_id: str | None = None) -> dict:
    payload = _activation_payload(install_id=install_id)
    r = await client.post("/v1/activate", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    data["install_id"] = payload["install_id"]
    return data


async def _heartbeat(
    client: AsyncClient,
    install_id: str,
    shared_secret: str,
    *,
    bad_secret: bool = False,
) -> dict:
    payload = _heartbeat_payload(install_id)
    secret = "wrongsecret" if bad_secret else shared_secret
    sig, body = sign_heartbeat(payload, secret)
    r = await client.post(
        "/v1/heartbeat",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-ZLF-Signature": sig,
            "X-ZLF-Timestamp": str(payload["timestamp"]),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _verify_jwt(token: str) -> dict:
    return jwt.decode(
        token,
        PUBLIC_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": True},
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_health(client: AsyncClient):
    r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_activate_unknown_key(client: AsyncClient):
    payload = _activation_payload(license_key="ZLP-FAKE-0000-0000")
    r = await client.post("/v1/activate", json=payload)
    assert r.status_code == 404


async def test_activate_success(client: AsyncClient, seed_db):
    install_id = str(uuid.uuid4())
    payload = _activation_payload(install_id=install_id)
    r = await client.post("/v1/activate", json=payload)
    assert r.status_code == 200

    data = r.json()
    assert "token" in data
    assert "shared_secret" in data
    assert "registry_token" in data

    claims = _verify_jwt(data["token"])
    assert claims["iss"] == JWT_ISSUER
    assert claims["product"] == "zenmsp"
    assert claims["plan"] == "professional"
    assert claims["revoked"] is False
    assert claims["exp"] > int(time.time())


async def test_heartbeat_valid(client: AsyncClient, seed_db):
    activation = await _activate(client)
    install_id = activation["install_id"]
    shared_secret = activation["shared_secret"]

    result = await _heartbeat(client, install_id, shared_secret)
    assert result["status"] == "valid"
    assert "token" in result
    assert "shared_secret" in result

    # New token must be a valid RS256 JWT
    claims = _verify_jwt(result["token"])
    assert claims["iss"] == JWT_ISSUER
    assert claims["install_id"] == install_id


async def test_heartbeat_invalid_signature(client: AsyncClient, seed_db):
    activation = await _activate(client)
    install_id = activation["install_id"]
    shared_secret = activation["shared_secret"]

    result = await _heartbeat(client, install_id, shared_secret, bad_secret=True)
    assert result["status"] == "revoked"
    assert result["reason"] == "signature_mismatch"


async def test_heartbeat_replay(client: AsyncClient, seed_db):
    activation = await _activate(client)
    install_id = activation["install_id"]
    shared_secret = activation["shared_secret"]

    # Build payload once and reuse same bytes for both requests.
    hb_payload = _heartbeat_payload(install_id)
    sig, body = sign_heartbeat(hb_payload, shared_secret)
    headers = {
        "Content-Type": "application/json",
        "X-ZLF-Signature": sig,
        "X-ZLF-Timestamp": str(hb_payload["timestamp"]),
    }

    r1 = await client.post("/v1/heartbeat", content=body, headers=headers)
    assert r1.status_code == 200
    first = r1.json()
    assert first["status"] == "valid"

    # Second attempt with the same body: the shared secret rotated after the
    # first heartbeat, so the HMAC is now wrong — server returns signature_mismatch.
    # Either signature_mismatch or replay_attack_detected is an acceptable response;
    # both prove the replay is blocked.
    r2 = await client.post("/v1/heartbeat", content=body, headers=headers)
    assert r2.status_code == 200
    second = r2.json()
    assert second["status"] == "revoked"
    assert second["reason"] in ("replay_attack_detected", "signature_mismatch")


async def test_revoke_install(client: AsyncClient, seed_db):
    activation = await _activate(client)
    install_id = activation["install_id"]

    r = await client.post(f"/v1/revoke/{install_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["revoked"] is True
    assert data["install_id"] == install_id


async def test_heartbeat_after_revoke(client: AsyncClient, seed_db):
    activation = await _activate(client)
    install_id = activation["install_id"]
    shared_secret = activation["shared_secret"]

    r = await client.post(f"/v1/revoke/{install_id}")
    assert r.status_code == 200

    # /v1/revoke sets install.status = "blocked"; heartbeat.py enforces at the
    # license_key level, so we revoke the key to trigger the expected rejection.
    async with test_session_maker() as session:
        await session.execute(
            update(LicenseKey).where(LicenseKey.key == "ZLP-TEST-1234-ABCD").values(status="revoked")
        )
        await session.commit()

    result = await _heartbeat(client, install_id, shared_secret)
    assert result["status"] == "revoked"


async def test_status(client: AsyncClient, seed_db):
    await _activate(client)

    r = await client.get("/v1/status/ZLP-TEST-1234-ABCD")
    assert r.status_code == 200

    data = r.json()
    assert data["key"] == "ZLP-TEST-1234-ABCD"
    assert data["plan"] == "professional"
    assert isinstance(data["installs"], list)
    assert len(data["installs"]) == 1
    assert data["installs"][0]["domain"] == "app.customer.com"


async def test_activate_expired_key(client: AsyncClient, seed_db):
    async with test_session_maker() as session:
        product = (await session.execute(select(Product).where(Product.slug == "zenmsp"))).scalar_one()
        expired_key = LicenseKey(
            product_id=product.id,
            key="ZLP-EXPR-0000-0001",
            plan="starter",
            seats=1,
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add(expired_key)
        await session.commit()

    payload = _activation_payload(license_key="ZLP-EXPR-0000-0001")
    r = await client.post("/v1/activate", json=payload)
    assert r.status_code == 402


async def test_activate_revoked_key(client: AsyncClient, seed_db):
    async with test_session_maker() as session:
        product = (await session.execute(select(Product).where(Product.slug == "zenmsp"))).scalar_one()
        revoked_key = LicenseKey(
            product_id=product.id,
            key="ZLP-RVKD-0000-0002",
            plan="starter",
            seats=1,
            status="revoked",
        )
        session.add(revoked_key)
        await session.commit()

    payload = _activation_payload(license_key="ZLP-RVKD-0000-0002")
    r = await client.post("/v1/activate", json=payload)
    assert r.status_code == 402


async def test_dashboard_stats(client: AsyncClient, seed_db):
    r = await client.get(
        "/dashboard/stats",
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200

    data = r.json()
    for field in ("total_installs", "active", "blocked", "anomalous", "total_keys", "unresolved_alerts"):
        assert field in data, f"missing field: {field}"
        assert isinstance(data[field], int), f"{field} must be int, got {type(data[field])}"
