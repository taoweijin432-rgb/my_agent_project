import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[redacted]"
SENSITIVE_KEY_PATTERN = (
    r"authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|password|passwd|pwd|"
    r"secret|client[-_]?secret|api[-_]?key|access[-_]?token|refresh[-_]?token|"
    r"id[-_]?token|auth[-_]?token|session[-_]?token|private[-_]?key|zhipu[-_]?api[-_]?key"
)
SENSITIVE_FIELD_PATTERN = (
    rf"{SENSITIVE_KEY_PATTERN}|x[-_]api[-_]key|x[-_]auth[-_]token|"
    rf"x[-_]csrf[-_]token|x[-_]xsrf[-_]token"
)
_SENSITIVE_HEADER_RE = re.compile(
    rf"(?im)^(\s*(?:{SENSITIVE_FIELD_PATTERN})\s*:\s*).+$"
)
_SENSITIVE_KEY_RE = re.compile(rf"(?i)^(?:{SENSITIVE_FIELD_PATTERN})$")
_JSON_SECRET_RE = re.compile(
    rf"""(?ix)((["'])(?:{SENSITIVE_FIELD_PATTERN})\2\s*:\s*)(["'])(.*?)\3"""
)
_ASSIGNMENT_SECRET_RE = re.compile(
    rf"""(?ix)(\b(?:{SENSITIVE_FIELD_PATTERN})\b\s*[:=]\s*)(["']?)[^\s,;]+(["']?)"""
)
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_URL_PASSWORD_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@\s/]+(@)")
_SENSITIVE_JSON_ASSERTION_RE = re.compile(
    rf"""(?ix)(
        JSON\ assertion\ failed:\s*path\s+
        \S*(?:{SENSITIVE_FIELD_PATTERN})\S*
        \s+expected\s+
    )
    (?:"[^"]*"|'[^']*'|[^\s]+)
    (\s+but\s+got\s+)
    (?:"[^"]*"|'[^']*'|[^\s.]+)
    """
)


def redact_sensitive_text(content: str) -> str:
    if not content:
        return content

    redacted = _SENSITIVE_HEADER_RE.sub(rf"\1{REDACTED}", content)
    redacted = _JSON_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(3)}{REDACTED}{match.group(3)}",
        redacted,
    )
    redacted = _SENSITIVE_JSON_ASSERTION_RE.sub(
        rf'\1"{REDACTED}"\2"{REDACTED}"',
        redacted,
    )
    redacted = _AUTH_SCHEME_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    redacted = _ASSIGNMENT_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}{match.group(3)}",
        redacted,
    )
    return _URL_PASSWORD_RE.sub(rf"\1{REDACTED}\2", redacted)


def redact_sensitive_texts(values: list[str]) -> list[str]:
    return [redact_sensitive_text(value) for value in values]


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if _is_sensitive_key(key) and item is not None
                else redact_sensitive_data(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY_RE.match(key.strip()))
