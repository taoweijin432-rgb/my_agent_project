from urllib.parse import quote

import pytest
from pydantic import ValidationError

from app.api import routes
from app.models.test_case import ExportRequest
from app.services.excel_exporter import build_excel


CASE = {
    "id": "TC-001",
    "title": "登录成功",
    "precondition": "用户已注册",
    "steps": ["输入手机号", "输入验证码", "点击登录"],
    "expected": ["登录成功"],
    "type": "functional",
}


def _export_request(filename: str | None = None) -> ExportRequest:
    return ExportRequest.model_validate(
        {"cases": [CASE], "filename": filename}
        if filename is not None
        else {"cases": [CASE]}
    )


def _export_response(filename: str | None = None):
    return routes.export_test_cases(_export_request(filename))


def test_export_builds_xlsx_content() -> None:
    content = build_excel(_export_request().cases).getvalue()
    assert content.startswith(b"PK")


def test_export_appends_xlsx_and_sets_safe_content_disposition() -> None:
    response = _export_response("login-cases")

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
    response = _export_response(filename)

    assert f"filename*=UTF-8''{quote(filename, safe='')}" in response.headers[
        "content-disposition"
    ]


def test_export_rejects_header_injection_filename() -> None:
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(
            {"cases": [CASE], "filename": "bad\r\nX-Injected: value.xlsx"}
        )
