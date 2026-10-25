"""Cloudflare Access gate for the public deployment.

When the app is reached through a Cloudflare Tunnel every request arrives from 127.0.0.1, so the
loopback checks in main.py no longer tell users apart. Cloudflare Access does the login; this module
verifies the signed Access token (JWT) on every request, so a missing or misconfigured Access policy
fails closed instead of exposing the app and the stored AI key.

Requests addressed to localhost (Host: 127.0.0.1 / localhost) skip the check: the server only listens
on the loopback interface, so those can only come from this machine.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
CERT_CACHE_SECONDS = 3600


class AccessDenied(Exception):
    pass


def _b64url(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class AccessVerifier:
    def __init__(self, team_domain: str, audience: str) -> None:
        domain = team_domain.strip().removeprefix("https://").rstrip("/")
        if not domain or not audience.strip():
            raise ValueError("Cloudflare Access team domain and AUD tag are required")
        self.issuer = f"https://{domain}"
        self.certs_url = f"{self.issuer}/cdn-cgi/access/certs"
        self.audience = audience.strip()
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._fetched_at = 0.0

    def _fetch_keys(self) -> dict[str, rsa.RSAPublicKey]:
        response = httpx.get(self.certs_url, timeout=10)
        response.raise_for_status()
        keys = {}
        for jwk in response.json().get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("kid"):
                numbers = rsa.RSAPublicNumbers(int.from_bytes(_b64url(jwk["e"]), "big"), int.from_bytes(_b64url(jwk["n"]), "big"))
                keys[jwk["kid"]] = numbers.public_key()
        return keys

    def _key(self, kid: str) -> rsa.RSAPublicKey:
        stale = time.time() - self._fetched_at > CERT_CACHE_SECONDS
        if stale or kid not in self._keys:  # refresh on expiry or key rotation
            self._keys = self._fetch_keys()
            self._fetched_at = time.time()
        if kid not in self._keys:
            raise AccessDenied("unknown signing key")
        return self._keys[kid]

    def verify(self, token: str) -> dict[str, Any]:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
            header = json.loads(_b64url(header_b64))
            claims = json.loads(_b64url(payload_b64))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AccessDenied("malformed token") from exc
        if header.get("alg") != "RS256":
            raise AccessDenied("unexpected algorithm")
        try:
            self._key(header.get("kid", "")).verify(
                _b64url(signature_b64), f"{header_b64}.{payload_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
            )
        except InvalidSignature as exc:
            raise AccessDenied("bad signature") from exc
        audience = claims.get("aud")
        if self.audience not in (audience if isinstance(audience, list) else [audience]):
            raise AccessDenied("wrong audience")
        if claims.get("iss") != self.issuer:
            raise AccessDenied("wrong issuer")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < time.time():
            raise AccessDenied("expired token")
        return claims


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, verifier: AccessVerifier) -> None:
        super().__init__(app)
        self.verifier = verifier

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if host in LOCAL_HOSTS:
            return await call_next(request)
        token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
        if not token:
            return JSONResponse({"detail": "Sign-in through Cloudflare Access is required."}, status_code=401)
        try:
            claims = self.verifier.verify(token)
        except (AccessDenied, httpx.HTTPError):
            return JSONResponse({"detail": "Cloudflare Access sign-in could not be verified."}, status_code=403)
        request.state.access_email = claims.get("email")
        return await call_next(request)
