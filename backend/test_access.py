import base64
import json
import time
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.access import AccessDenied, AccessVerifier, CloudflareAccessMiddleware

TEAM = "team.cloudflareaccess.com"
AUD = "aud-tag-123"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(key, kid="k1", **overrides) -> str:
    claims = {"aud": [AUD], "iss": f"https://{TEAM}", "exp": time.time() + 600, "email": "member@u.nus.edu"} | overrides
    signing_input = f"{b64(json.dumps({'alg': 'RS256', 'kid': kid}).encode())}.{b64(json.dumps(claims).encode())}"
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{b64(signature)}"


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = AccessVerifier(TEAM, AUD)
        self.verifier._fetch_keys = lambda: {"k1": self.key.public_key()}

        app = FastAPI()
        app.add_middleware(CloudflareAccessMiddleware, verifier=self.verifier)

        @app.get("/api/v1/ping")
        def ping():
            return {"ok": True}

        self.client = TestClient(app)

    def test_valid_token_passes_and_bad_tokens_fail(self):
        self.assertEqual(self.verifier.verify(make_token(self.key))["email"], "member@u.nus.edu")
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for token in (make_token(other), make_token(self.key, aud=["other"]), make_token(self.key, exp=time.time() - 5),
                      make_token(self.key, iss="https://evil.example"), make_token(self.key, kid="unknown"), "not.a.jwt"):
            with self.assertRaises(AccessDenied):
                self.verifier.verify(token)

    def test_public_requests_need_a_valid_access_token(self):
        public = {"host": "copilot.example.com"}
        self.assertEqual(self.client.get("/api/v1/ping", headers=public).status_code, 401)
        forged = public | {"cf-access-jwt-assertion": make_token(rsa.generate_private_key(public_exponent=65537, key_size=2048))}
        self.assertEqual(self.client.get("/api/v1/ping", headers=forged).status_code, 403)
        signed = public | {"cf-access-jwt-assertion": make_token(self.key)}
        self.assertEqual(self.client.get("/api/v1/ping", headers=signed).status_code, 200)
        self.client.cookies.set("CF_Authorization", make_token(self.key))
        self.assertEqual(self.client.get("/api/v1/ping", headers=public).status_code, 200)

    def test_localhost_requests_skip_the_check(self):
        self.assertEqual(self.client.get("/api/v1/ping", headers={"host": "127.0.0.1:8000"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
