"""Reactive WAF fingerprint classifier.

Pure: no I/O, no exceptions. Called by every tier tool after a 4xx
response. The result drives `*Failure.reason`:

- `cloudflare` → HTTP tier escalates to stealth (`protected_cloudflare`),
  stealth tier escalates to dynamic (`javascript_required`), dynamic
  tier terminates (`upstream_error`).
- `akamai` / `datadome` / `perimeterx` → terminate as
  `site_not_supported` regardless of tier (out of MVP scope per
  `project-overview.md`).
- `unknown` (4xx without a matching fingerprint) → terminate as
  `upstream_error`.

Status codes outside `{403, 429, 503}` short-circuit to `None` so callers
do not invoke detection on healthy responses.
"""

from __future__ import annotations

from typing import Literal

WafKind = Literal["cloudflare", "akamai", "datadome", "perimeterx", "unknown"]

# WAF kinds whose detection is treated as terminal — the agent surfaces
# `site_not_supported` and does not retry. The MVP does not attempt
# bypass for these (per `project-overview.md` scope).
TERMINAL_WAFS: frozenset[WafKind] = frozenset({"akamai", "datadome", "perimeterx"})


def body_excerpt(body: object, limit: int = 4096) -> str:
    """Best-effort string excerpt of an HTTP response body for WAF
    fingerprinting. Accepts bytes, `None`, or any string-coercible
    value (Scrapling 0.2.99 returns a `TextHandler`, a `str` subclass).
    """
    if isinstance(body, bytes):
        return body[:limit].decode("utf-8", errors="replace")
    if body is None:
        return ""
    return str(body)[:limit]


def detect_waf(
    *,
    status: int,
    headers: dict[str, str],
    body_excerpt: str,
) -> WafKind | None:
    """Classify a 4xx response by WAF fingerprint.

    Returns `None` when the response does not look WAF-blocked.
    Header keys/values are lower-cased internally so callers can pass
    the dict verbatim from any HTTP client.
    """
    if status not in {403, 429, 503}:
        return None

    h = {k.lower(): v.lower() for k, v in headers.items()}
    body = body_excerpt.lower()

    if "cloudflare" in h.get("server", ""):
        return "cloudflare"
    if "cf-ray" in h or "cf-mitigated" in h:
        return "cloudflare"
    if "checking your browser" in body:
        return "cloudflare"

    if "akamaighost" in h.get("server", ""):
        return "akamai"
    if "x-akamai" in h or any(k.startswith("ak-") for k in h):
        return "akamai"

    if "x-datadome" in h or "datadome" in h.get("set-cookie", ""):
        return "datadome"

    if "x-iinfo" in h or "_pxhd" in h.get("set-cookie", ""):
        return "perimeterx"
    if "px-captcha" in body:
        return "perimeterx"

    return "unknown"
