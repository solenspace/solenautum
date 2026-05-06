from __future__ import annotations

import pytest

from app.tools._waf import detect_waf


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected"),
    [
        (403, {"server": "cloudflare", "cf-ray": "abc123"}, "", "cloudflare"),
        (503, {"server": "nginx"}, "Checking your browser before accessing", "cloudflare"),
        (403, {"server": "AkamaiGHost"}, "", "akamai"),
        (403, {"x-datadome": "blocked"}, "", "datadome"),
        (403, {"x-iinfo": "P-9 ..."}, "", "perimeterx"),
        (200, {}, "", None),
        (404, {"server": "nginx"}, "", None),
        (403, {"server": "nginx"}, "Generic forbidden", "unknown"),
    ],
)
def test_classifies(status: int, headers: dict[str, str], body: str, expected: object) -> None:
    assert detect_waf(status=status, headers=headers, body_excerpt=body) == expected
