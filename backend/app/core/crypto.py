"""AES-256-GCM primitives for conversation history at rest.

Envelope scheme: a key-encryption key (KEK) from the environment wraps a
per-conversation data key (DEK); message bodies and conversation titles are
sealed with the DEK. A per-conversation key bounds what a leaked data key
exposes and turns KEK rotation into a rewrap of the stored keys instead of a
re-encryption of every row. Every sealed payload is bound to its row through
associated data (the message or conversation id), so a ciphertext cannot be
moved to another row and still open.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
TOKEN_PREFIX = "enc:v1:"


class DecryptionError(Exception):
    """A stored payload failed to open (wrong key, tampering, bad format)."""


class InvalidKeyError(ValueError):
    """The configured key is not a base64-encoded 32-byte value."""


class Cipher:
    """Seals and opens values with one AES-256-GCM key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise InvalidKeyError(f"expected a {KEY_BYTES}-byte key, got {len(key)}")
        self._aead = AESGCM(key)

    def seal(self, data: bytes, *, context: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, data, context.encode())
        nonce_text = base64.b64encode(nonce).decode()
        body_text = base64.b64encode(sealed).decode()
        return f"{TOKEN_PREFIX}{nonce_text}:{body_text}"

    def open(self, token: str, *, context: str) -> bytes:
        if not token.startswith(TOKEN_PREFIX):
            raise DecryptionError("not an encrypted value")
        nonce_text, _, body_text = token.removeprefix(TOKEN_PREFIX).partition(":")
        if not nonce_text or not body_text:
            raise DecryptionError("malformed ciphertext token")
        try:
            nonce = base64.b64decode(nonce_text, validate=True)
            body = base64.b64decode(body_text, validate=True)
        except binascii.Error as exc:
            raise DecryptionError("malformed ciphertext token") from exc
        if len(nonce) != NONCE_BYTES:
            raise DecryptionError("malformed ciphertext token")
        try:
            return self._aead.decrypt(nonce, body, context.encode())
        except InvalidTag as exc:
            raise DecryptionError("ciphertext failed authentication") from exc


def generate_key() -> str:
    """A fresh base64 key-encryption key, for the environment or a rotation."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode()


def decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidKeyError("key is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise InvalidKeyError(f"key must decode to {KEY_BYTES} bytes")
    return key


def is_token(value: str | None) -> bool:
    """Whether a stored value is a sealed payload rather than legacy plaintext."""
    return value is not None and value.startswith(TOKEN_PREFIX)


def get_cipher() -> Cipher | None:
    """The configured cipher, or None when no key is set (plaintext mode)."""
    key = get_settings().encryption_key.strip()
    if not key:
        return None
    return Cipher(decode_key(key))


def seal_text(cipher: Cipher, text: str, *, context: str) -> str:
    return cipher.seal(text.encode("utf-8"), context=context)


def open_text(cipher: Cipher, token: str, *, context: str) -> str:
    try:
        return cipher.open(token, context=context).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptionError("decrypted payload is not valid text") from exc
