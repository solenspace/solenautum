from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_me_rejects_missing_token() -> None:
    response = client.get("/me")
    assert response.status_code == 401


def test_me_rejects_garbage_token() -> None:
    response = client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
