from __future__ import annotations

import socket

import pytest

from app import security
from app.config import settings
from app.security import UrlNotAllowed, assert_safe_url


def _fake_public_dns(_hostname: str, _port: object) -> list[tuple[object, ...]]:
    # Pretend the hostname resolves to a public IP so the SSRF guard
    # passes and the allow-list logic is the only thing under test.
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def test_no_allowlist_permits_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", None)
    monkeypatch.setattr(security.socket, "getaddrinfo", _fake_public_dns)
    assert_safe_url("https://example.com/")


def test_allowlist_blocks_off_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", "example.com")
    monkeypatch.setattr(security.socket, "getaddrinfo", _fake_public_dns)
    with pytest.raises(UrlNotAllowed):
        assert_safe_url("https://other.com/")


def test_allowlist_glob_matches_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", "*.example.com")
    monkeypatch.setattr(security.socket, "getaddrinfo", _fake_public_dns)
    assert_safe_url("https://api.example.com/")
