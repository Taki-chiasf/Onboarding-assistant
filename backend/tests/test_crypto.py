import base64

import pytest

from app.core.config import get_settings
from app.core.crypto import (
    KEY_BYTES,
    TOKEN_PREFIX,
    Cipher,
    DecryptionError,
    InvalidKeyError,
    decode_key,
    generate_key,
    get_cipher,
    is_token,
    open_text,
    seal_text,
)


def _cipher() -> Cipher:
    return Cipher(b"k" * KEY_BYTES)


def test_seal_open_round_trip() -> None:
    cipher = _cipher()

    token = cipher.seal(b"secret", context="message:1")

    assert token.startswith(TOKEN_PREFIX)
    assert "secret" not in token
    assert cipher.open(token, context="message:1") == b"secret"


def test_each_seal_uses_a_fresh_nonce() -> None:
    cipher = _cipher()

    first = cipher.seal(b"same", context="row")
    second = cipher.seal(b"same", context="row")

    assert first != second
    assert cipher.open(first, context="row") == b"same"
    assert cipher.open(second, context="row") == b"same"


def test_open_binds_the_ciphertext_to_its_context() -> None:
    cipher = _cipher()

    token = cipher.seal(b"secret", context="message:1")

    with pytest.raises(DecryptionError):
        cipher.open(token, context="message:2")


def test_open_rejects_tampering() -> None:
    cipher = _cipher()
    token = cipher.seal(b"secret", context="row")
    head, _, body = token.rpartition(":")
    flipped = "A" if body[0] != "A" else "B"
    tampered = f"{head}:{flipped}{body[1:]}"

    with pytest.raises(DecryptionError):
        cipher.open(tampered, context="row")


def test_open_rejects_a_wrong_key() -> None:
    token = Cipher(b"a" * KEY_BYTES).seal(b"secret", context="row")

    with pytest.raises(DecryptionError):
        Cipher(b"b" * KEY_BYTES).open(token, context="row")


@pytest.mark.parametrize(
    "token",
    ["", "plain", TOKEN_PREFIX, f"{TOKEN_PREFIX}only-nonce", f"{TOKEN_PREFIX}!!!!:!!!!"],
)
def test_open_rejects_malformed_tokens(token: str) -> None:
    with pytest.raises(DecryptionError):
        _cipher().open(token, context="row")


def test_cipher_requires_a_32_byte_key() -> None:
    with pytest.raises(InvalidKeyError):
        Cipher(b"short")


def test_generate_key_round_trips_through_decode() -> None:
    value = generate_key()

    assert len(decode_key(value)) == KEY_BYTES
    assert base64.b64encode(decode_key(value)).decode() == value


@pytest.mark.parametrize("value", ["", "not base64!", base64.b64encode(b"short").decode()])
def test_decode_key_rejects_invalid_values(value: str) -> None:
    with pytest.raises(InvalidKeyError):
        decode_key(value)


def test_is_token() -> None:
    assert is_token(f"{TOKEN_PREFIX}abc:def")
    assert not is_token("plain text")
    assert not is_token("")
    assert not is_token(None)


def test_text_helpers_round_trip_unicode() -> None:
    cipher = _cipher()

    token = seal_text(cipher, "Grüße — 16 weeks", context="title")

    assert open_text(cipher, token, context="title") == "Grüße — 16 weeks"


def test_get_cipher_reads_the_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    assert get_cipher() is None

    value = generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", value)
    get_settings.cache_clear()
    cipher = get_cipher()
    assert cipher is not None
    assert cipher.open(cipher.seal(b"x", context="row"), context="row") == b"x"

    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-key")
    get_settings.cache_clear()
    try:
        with pytest.raises(InvalidKeyError):
            get_cipher()
    finally:
        get_settings.cache_clear()
