"""Sign-in -> supernode linking. The supernode is built by the USER signing in
with their FERN account (the consent moment), never by behind-the-back matching.

This module is provider-agnostic: it verifies a signed identity token and maps it
to a stable person_id, then links the current site's local user into that person's
supernode. A MockProvider is included so the flow is testable end-to-end without a
real IdP; a real Google/GitHub OIDC verifier drops in behind the same interface."""
from __future__ import annotations
import hmac, hashlib, json, base64, time
from typing import Optional


def _b64(d: bytes) -> str: return base64.urlsafe_b64encode(d).decode().rstrip("=")
def _unb64(s: str) -> bytes: return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class MockProvider:
    """Stand-in identity provider: issues and verifies HMAC-signed tokens. Mirrors
    the contract of a real OIDC id_token (issuer, subject, expiry, signature)."""
    def __init__(self, secret: bytes = b"mock-idp-secret", issuer: str = "mock-idp"):
        self.secret = secret; self.issuer = issuer

    def issue(self, subject: str, email: str = "", ttl: int = 3600) -> str:
        body = {"iss": self.issuer, "sub": subject, "email": email,
                "exp": int(time.time()) + ttl}
        payload = _b64(json.dumps(body, sort_keys=True).encode())
        sig = _b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{sig}"

    def verify(self, token: str) -> dict:
        try:
            payload, sig = token.split(".")
        except ValueError:
            raise AuthError("malformed token")
        expect = _b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            raise AuthError("bad signature")              # tamper / forgery
        body = json.loads(_unb64(payload))
        if body.get("exp", 0) < time.time():
            raise AuthError("token expired")
        if body.get("iss") != self.issuer:
            raise AuthError("untrusted issuer")
        return body


class AuthError(RuntimeError):
    pass


def person_id_for(claims: dict) -> str:
    """Stable, opaque person id from verified claims (issuer+subject). Never the
    raw email -> identities aren't linkable by guessing an address."""
    raw = f"{claims['iss']}:{claims['sub']}".encode()
    return "person:" + hashlib.sha256(raw).hexdigest()[:16]


def sign_in_and_link(service, provider, token: str, site: str, local_user: str) -> dict:
    """The whole handshake: verify the token, derive the person, link THIS site's
    local user into their supernode. Consent is implicit in the user choosing to
    sign in with their FERN identity here."""
    claims = provider.verify(token)               # raises AuthError on tamper/expiry
    person = person_id_for(claims)
    service.link_identity(person, site, local_user)
    return {"person": person, "linked": service.store.list_identities(person)}
