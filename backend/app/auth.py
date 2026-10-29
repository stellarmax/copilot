"""Accounts for the web app: session cookies, login throttling and invite-only registration.

Every /api/v1 endpoint except /api/v1/auth/* requires a signed-in user. Each user's AI key, chats,
memories, reminders and action log are private to them; the factory data is shared and read-only.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.agent.store import SESSION_DAYS, AgentStore

SESSION_COOKIE = "copilot_session"
PUBLIC_API_PREFIX = "/api/v1/auth/"
LOCAL_HOST_NAMES = {"127.0.0.1", "localhost", "[::1]"}
MAX_FAILURES, FAILURE_WINDOW_SECONDS = 5, 15 * 60


def is_local_request(request: Request) -> bool:
    """True only for a browser on this computer: loopback client *and* a localhost Host header.

    A Cloudflare Tunnel also connects from 127.0.0.1, but it keeps the public Host header.
    """
    host = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    host_name = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    return loopback and host_name in LOCAL_HOST_NAMES


def check_invite(request: Request, code: str | None) -> None:
    expected = os.getenv("COPILOT_INVITE_CODE", "")
    if expected:
        if not code or not hmac.compare_digest(code.strip(), expected):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The invite code is not valid.")
    elif not is_local_request(request):
        # Without a configured invite code, accounts can only be created on the host computer.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is closed.")


class LoginThrottle:
    """At most MAX_FAILURES failed sign-ins per e-mail and per client within the window."""

    def __init__(self) -> None:
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def _keys(self, email: str, request: Request) -> list[str]:
        client = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
        return [f"email:{email}", f"client:{client}"]

    def _recent(self, key: str) -> deque[float]:
        entries, cutoff = self.failures[key], time.monotonic() - FAILURE_WINDOW_SECONDS
        while entries and entries[0] < cutoff:
            entries.popleft()
        return entries

    def check(self, email: str, request: Request) -> None:
        if any(len(self._recent(key)) >= MAX_FAILURES for key in self._keys(email, request)):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Too many failed sign-ins. Try again in 15 minutes.")

    def record_failure(self, email: str, request: Request) -> None:
        for key in self._keys(email, request):
            self.failures[key].append(time.monotonic())

    def reset(self, email: str, request: Request) -> None:
        for key in self._keys(email, request):
            self.failures.pop(key, None)


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=_is_https(request), path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(request: Request) -> dict[str, str]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    return user


class SessionMiddleware(BaseHTTPMiddleware):
    """Resolve the session cookie for every request and block signed-out API calls."""

    async def dispatch(self, request: Request, call_next):
        request.state.user = None
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            store = AgentStore(request.app.state.db_path)
            try:
                request.state.user = store.session_user(token)
            finally:
                store.close()
        path = request.url.path
        if path.startswith("/api/") and not path.startswith(PUBLIC_API_PREFIX) and request.state.user is None:
            return JSONResponse({"detail": "Please sign in."}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)
