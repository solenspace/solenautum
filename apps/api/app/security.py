from __future__ import annotations

import ipaddress
import socket
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from clerk_backend_api.security.authenticaterequest import authenticate_request_async
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# --- request-scoped user context -----------------------------------------


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str
    session_id: str


_current_user: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)


def get_current_user() -> CurrentUser:
    """Return the user bound to this request. Raises 401 if unset."""
    user = _current_user.get()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


# --- Clerk verification --------------------------------------------------


async def require_user(request: Request) -> CurrentUser:
    """FastAPI dependency: verify the Clerk JWT and bind user to context."""
    state = await authenticate_request_async(
        request,
        AuthenticateRequestOptions(secret_key=settings.clerk_secret_key),
    )
    if not state.is_signed_in:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    payload = state.payload
    if payload is None or "sub" not in payload or "sid" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")

    user = CurrentUser(user_id=str(payload["sub"]), session_id=str(payload["sid"]))
    _current_user.set(user)
    return user


RequireUser = Annotated[CurrentUser, Depends(require_user)]


# --- SSRF guard (invariant 1) --------------------------------------------

_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlNotAllowed(HTTPException):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"url": url, "reason": reason},
        )


def assert_safe_url(url: str) -> None:
    """Reject SSRF + non-allowlisted URLs. Called by every fetcher tier."""
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlNotAllowed(url, "scheme not allowed")
    if not parsed.hostname:
        raise UrlNotAllowed(url, "missing hostname")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UrlNotAllowed(url, "dns resolution failed") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise UrlNotAllowed(url, "private address blocked")

    patterns = settings.allowlist_patterns
    if patterns and not any(_matches(parsed.hostname, p) for p in patterns):
        raise UrlNotAllowed(url, "domain not in allow-list")


def _matches(hostname: str, pattern: str) -> bool:
    """Match `*.example.com` style patterns. Plain domains match exactly."""
    if pattern.startswith("*."):
        return hostname == pattern[2:] or hostname.endswith("." + pattern[2:])
    return hostname == pattern


# --- robots.txt (invariant 11) -------------------------------------------

_robots_cache: dict[str, RobotFileParser] = {}


async def assert_robots_allows(url: str, *, robots_override: bool = False) -> None:
    """Honor robots.txt unless the mission carries a user-attributed override."""
    if robots_override:
        return

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"
    parser = _robots_cache.get(base)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(f"{base}/robots.txt")
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": settings.autumn_user_agent},
                timeout=5.0,
            ) as client:
                resp = await client.get(f"{base}/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # No robots.txt → permissive (stdlib semantics).
                    parser.allow_all = True  # type: ignore[attr-defined]  # stdlib attr, missing from typeshed
        except (httpx.HTTPError, OSError):
            # Failing closed on a network error would let robots.txt
            # outages block all scraping; fail-open matches stdlib intent.
            parser.allow_all = True  # type: ignore[attr-defined]  # stdlib attr, missing from typeshed
        _robots_cache[base] = parser

    if not parser.can_fetch(settings.autumn_user_agent, url):
        raise UrlNotAllowed(url, "robots.txt disallowed")


# --- rate limiter --------------------------------------------------------


def _user_id_or_remote(request: Request) -> str:
    user = _current_user.get()
    if user is not None:
        return user.user_id
    return get_remote_address(request)


limiter = Limiter(
    key_func=_user_id_or_remote,
    default_limits=["1000/day", "60/minute"],
    storage_uri="memory://",
)
