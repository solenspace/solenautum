from __future__ import annotations

from app.main import app


def test_app_exists() -> None:
    assert app.title == "Autumn API"
