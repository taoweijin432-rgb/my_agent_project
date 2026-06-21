from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.api.routes import require_api_key
from app.main import app


client = TestClient(app)


CASE = {
    "id": "TC-001",
    "title": "登录成功",
    "precondition": "用户已注册",
    "steps": ["输入手机号", "输入验证码", "点击登录"],
    "expected": ["登录成功"],
    "type": "functional",
}


@pytest.fixture(autouse=True)
def bypass_api_key() -> None:
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


def test_export_appends_xlsx_and_sets_safe_content_disposition() -> None:
    response = client.post(
        "/api/v1/test-cases/export",
        json={"cases": [CASE], "filename": "login-cases"},
    )

    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert (
        response.headers["content-disposition"]
        == "attachment; filename=\"login-cases.xlsx\"; filename*=UTF-8''login-cases.xlsx"
    )


def test_export_supports_unicode_filename_with_encoded_header() -> None:
    filename = "登录用例.xlsx"
    response = client.post(
        "/api/v1/test-cases/export",
        json={"cases": [CASE], "filename": filename},
    )

    assert response.status_code == 200
    assert f"filename*=UTF-8''{quote(filename, safe='')}" in response.headers[
        "content-disposition"
    ]


def test_export_rejects_header_injection_filename() -> None:
    response = client.post(
        "/api/v1/test-cases/export",
        json={"cases": [CASE], "filename": "bad\r\nX-Injected: value.xlsx"},
    )

    assert response.status_code == 422
