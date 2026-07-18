from app.services.redaction import redact_sensitive_data, redact_sensitive_text


def test_redact_sensitive_text_covers_common_secret_shapes() -> None:
    content = "\n".join(
        [
            "Authorization: Bearer secret-token",
            "Set-Cookie: session=secret-cookie; HttpOnly",
            '{"access_token":"secret-access","password":"secret-password"}',
            '{"x-api-key":"secret-json-api-key"}',
            "ZHIPU_API_KEY=secret-zhipu-key",
            "x-api-key=secret-assignment-api-key",
            "DATABASE_URL=mysql://agent:secret-db-password@mysql:3306/agent",
            (
                'JSON assertion failed: path auth.x-api-key expected "expected-token" '
                'but got "actual-token".'
            ),
            "status=visible",
        ]
    )

    redacted = redact_sensitive_text(content)

    assert "secret-token" not in redacted
    assert "secret-cookie" not in redacted
    assert "secret-access" not in redacted
    assert "secret-password" not in redacted
    assert "secret-json-api-key" not in redacted
    assert "secret-zhipu-key" not in redacted
    assert "secret-assignment-api-key" not in redacted
    assert "secret-db-password" not in redacted
    assert "expected-token" not in redacted
    assert "actual-token" not in redacted
    assert "Authorization: [redacted]" in redacted
    assert '"access_token":"[redacted]"' in redacted
    assert '"x-api-key":"[redacted]"' in redacted
    assert "x-api-key=[redacted]" in redacted
    assert "DATABASE_URL=mysql://agent:[redacted]@mysql:3306/agent" in redacted
    assert (
        'JSON assertion failed: path auth.x-api-key expected "[redacted]" '
        'but got "[redacted]".'
    ) in redacted
    assert "status=visible" in redacted


def test_redact_sensitive_data_recurses_nested_values() -> None:
    payload = {
        "message": "api_key=secret-api-key",
        "items": ["Authorization: Bearer secret-token", {"password": "secret-password"}],
        "count": 1,
    }

    redacted = redact_sensitive_data(payload)

    assert redacted == {
        "message": "api_key=[redacted]",
        "items": ["Authorization: [redacted]", {"password": "[redacted]"}],
        "count": 1,
    }
