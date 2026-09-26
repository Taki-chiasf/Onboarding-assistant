from app.core.redact import redact_pii


def test_redact_pii_replaces_email() -> None:
    assert redact_pii("email alice@example.com please") == "email [email] please"


def test_redact_pii_replaces_phone() -> None:
    assert redact_pii("call +1 555 123 4567 now") == "call [phone] now"


def test_redact_pii_replaces_ip_address() -> None:
    assert redact_pii("host 10.0.0.5 is down") == "host [ip] is down"


def test_redact_pii_allows_caller_email() -> None:
    text = "reach out to alice@example.com or bob@corp.com"
    redacted = redact_pii(text, allow=["alice@example.com"])
    assert "alice@example.com" in redacted
    assert "bob@corp.com" not in redacted


def test_redact_pii_leaves_plain_text() -> None:
    assert redact_pii("how much leave do I get?") == "how much leave do I get?"
