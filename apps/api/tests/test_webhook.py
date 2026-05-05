from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from svix.webhooks import Webhook

from app.config import settings
from app.main import app
from app.persistence.repository import UserRepository

pytestmark = pytest.mark.skipif(
    settings.clerk_webhook_signing_secret is None,
    reason="CLERK_WEBHOOK_SIGNING_SECRET not configured",
)


client = TestClient(app)


def _signed_headers(body: bytes) -> dict[str, str]:
    assert settings.clerk_webhook_signing_secret is not None
    wh = Webhook(settings.clerk_webhook_signing_secret)
    msg_id = "msg_test"
    ts_dt = datetime.now(UTC)
    sig = wh.sign(msg_id, ts_dt, body.decode())
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(ts_dt.timestamp())),
        "svix-signature": sig,
        "content-type": "application/json",
    }


def test_rejects_unsigned():
    body = json.dumps({"type": "user.created", "data": {}}).encode()
    response = client.post("/webhooks/clerk", content=body)
    assert response.status_code == 401


def test_accepts_signed_user_created(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_upsert(self, *, user_id: str, email: str):
        captured["user_id"] = user_id
        captured["email"] = email

        class _U:
            pass

        return _U()

    monkeypatch.setattr(UserRepository, "upsert", fake_upsert)

    body = json.dumps(
        {
            "type": "user.created",
            "data": {
                "id": "user_test_1",
                "primary_email_address_id": "idn_1",
                "email_addresses": [{"id": "idn_1", "email_address": "a@b.com"}],
            },
        }
    ).encode()
    response = client.post("/webhooks/clerk", content=body, headers=_signed_headers(body))
    assert response.status_code == 204
    assert captured == {"user_id": "user_test_1", "email": "a@b.com"}


def test_unknown_event_type_silently_204(monkeypatch):
    async def fake_upsert(self, *, user_id, email):
        raise AssertionError("upsert should not run for unknown event types")

    monkeypatch.setattr(UserRepository, "upsert", fake_upsert)

    body = json.dumps({"type": "session.created", "data": {"id": "sess_1"}}).encode()
    response = client.post("/webhooks/clerk", content=body, headers=_signed_headers(body))
    assert response.status_code == 204
