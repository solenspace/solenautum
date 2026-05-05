from __future__ import annotations

import pytest

from app.security import UrlNotAllowed, assert_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",  # AWS metadata
        "http://[::1]/",
    ],
)
def test_blocks_private_addresses(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        assert_safe_url(url)


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)"],
)
def test_blocks_non_http_schemes(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        assert_safe_url(url)


def test_allows_public_https() -> None:
    assert_safe_url("https://example.com/")
