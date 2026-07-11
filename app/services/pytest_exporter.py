from io import BytesIO
from pprint import pformat

from app.models.test_case import PytestExportRequest


def build_pytest_template(request: PytestExportRequest) -> BytesIO:
    if request.adapter == "login_api":
        return _build_login_api_adapter(request)
    return _build_template_adapter(request)


def _build_template_adapter(request: PytestExportRequest) -> BytesIO:
    cases = [
        case.model_dump(mode="json")
        for case in request.cases
    ]
    cases_literal = pformat(cases, width=100, sort_dicts=False)
    skip_literal = "True" if request.skip_by_default else "False"
    content = f'''"""Generated pytest template for AI-generated test cases.

Fill `execute_case` with real API or UI automation actions before enabling execution.
"""

import os

import pytest


BASE_URL = os.getenv("{request.target_base_url_env}", "http://127.0.0.1:8000")
SKIP_BY_DEFAULT = {skip_literal}
TEST_CASES = {cases_literal}


def execute_case(case):
    """Map the natural-language case steps to executable automation code."""
    raise NotImplementedError(f"Implement automation steps for {{case['id']}}")


@pytest.mark.parametrize("case", TEST_CASES, ids=[case["id"] for case in TEST_CASES])
def test_generated_case(case):
    if SKIP_BY_DEFAULT:
        pytest.skip("Template case requires automation step implementation.")

    execute_case(case)
'''
    stream = BytesIO(content.encode("utf-8"))
    stream.seek(0)
    return stream


def _build_login_api_adapter(request: PytestExportRequest) -> BytesIO:
    cases = [
        case.model_dump(mode="json")
        for case in request.cases
    ]
    cases_literal = pformat(cases, width=100, sort_dicts=False)
    skip_literal = "True" if request.skip_by_default else "False"
    content = f'''"""Generated executable pytest adapter for login API cases.

Set {request.target_base_url_env}, LOGIN_USERNAME and LOGIN_PASSWORD before running against a real service.
Override LOGIN_ENDPOINT when the target project uses a different login path.
"""

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urljoin

import pytest


BASE_URL = os.getenv("{request.target_base_url_env}", "http://127.0.0.1:8000")
LOGIN_ENDPOINT = os.getenv("LOGIN_ENDPOINT", "/api/v1/auth/login")
TIMEOUT_SECONDS = float(os.getenv("LOGIN_TIMEOUT_SECONDS", "5"))
SKIP_BY_DEFAULT = {skip_literal}
TEST_CASES = {cases_literal}

SUCCESS_TERMS = ("成功", "正确", "有效", "正常", "success")
FAILURE_TERMS = ("失败", "错误", "无效", "过期", "锁定", "禁止", "异常", "fail", "invalid", "expired")
FAILURE_STATUS_CODES = {{400, 401, 403, 409, 422}}


def _case_text(case):
    parts = [
        case.get("id", ""),
        case.get("title", ""),
        case.get("precondition", ""),
        " ".join(case.get("steps", [])),
        " ".join(case.get("expected", [])),
        case.get("type", ""),
    ]
    return " ".join(str(part) for part in parts).lower()


def expected_success(case):
    text = _case_text(case)
    if any(term.lower() in text for term in FAILURE_TERMS):
        return False
    return any(term.lower() in text for term in SUCCESS_TERMS)


def build_login_payload(case):
    password = os.getenv("LOGIN_PASSWORD", "test-password")
    if not expected_success(case):
        password = os.getenv("INVALID_LOGIN_PASSWORD", "wrong-password")
    return {{
        "username": os.getenv("LOGIN_USERNAME", "test-user"),
        "password": password,
    }}


def post_json(path, payload):
    url = urljoin(BASE_URL.rstrip("/") + "/", path.lstrip("/"))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


@pytest.mark.parametrize("case", TEST_CASES, ids=[case["id"] for case in TEST_CASES])
def test_generated_login_case(case):
    if SKIP_BY_DEFAULT:
        pytest.skip("Set skip_by_default=false after configuring login adapter environment variables.")

    status, response_body = post_json(LOGIN_ENDPOINT, build_login_payload(case))
    if expected_success(case):
        assert 200 <= status < 300, f"Expected login success for {{case['id']}}, got {{status}}: {{response_body}}"
    else:
        assert status in FAILURE_STATUS_CODES, (
            f"Expected login failure for {{case['id']}}, got {{status}}: {{response_body}}"
        )
'''
    stream = BytesIO(content.encode("utf-8"))
    stream.seek(0)
    return stream
