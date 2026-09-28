'''Access token minting and verification.

Tokens are HMAC-signed: an encoded payload plus a signature, both base64url.
The format is internal to the platform; clients only see the opaque string.
'''

import base64
import hashlib
import hmac
import json
import time

from .settings import Settings


class TokenError(Exception):
    '''Raised when a token is malformed, expired, or badly signed.'''


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(signing_key: str, payload: str) -> str:
    digest = hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def mint_token(settings: Settings, subject: str, scopes: list[str]) -> str:
    '''Mint a token for a subject with the given scopes.'''
    payload = {
        "sub": subject,
        "scopes": scopes,
        "exp": int(time.time()) + settings.token_ttl_seconds,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return encoded + "." + _sign(settings.signing_key, encoded)


def verify_token(settings: Settings, token: str) -> dict:
    '''Return the token payload, or raise TokenError.

    Signature comparison is constant time; expiry is checked after the
    signature so a forged token never reaches the payload parser.
    '''
    parts = token.split(".")
    if len(parts) != 2:
        raise TokenError("malformed token")
    encoded, signature = parts
    if not hmac.compare_digest(_sign(settings.signing_key, encoded), signature):
        raise TokenError("signature mismatch")
    payload = json.loads(_b64decode(encoded))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("token expired")
    return payload
