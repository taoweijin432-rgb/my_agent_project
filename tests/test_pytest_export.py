import pytest

from app.models.test_case import PytestExportRequest
from app.services.pytest_exporter import build_pytest_template


CASE = {
    "id": "TC-001",
    "title": "登录成功",
    "precondition": "用户已注册",
    "steps": ["输入手机号", "输入验证码", "点击登录"],
    "expected": ["登录成功"],
    "type": "functional",
}

def test_build_pytest_template_skips_by_default() -> None:
    request = PytestExportRequest.model_validate(
        {
            "cases": [CASE],
            "target_base_url_env": "LOGIN_BASE_URL",
        }
    )

    content = build_pytest_template(request).getvalue().decode("utf-8")

    assert "BASE_URL = os.getenv(\"LOGIN_BASE_URL\"" in content
    assert "SKIP_BY_DEFAULT = True" in content
    assert "pytest.skip" in content
    assert "TC-001" in content
    assert "登录成功" in content


def test_build_login_api_adapter_is_executable_pytest() -> None:
    request = PytestExportRequest.model_validate(
        {
            "cases": [CASE],
            "target_base_url_env": "LOGIN_BASE_URL",
            "skip_by_default": False,
            "adapter": "login_api",
        }
    )

    content = build_pytest_template(request).getvalue().decode("utf-8")

    assert "BASE_URL = os.getenv(\"LOGIN_BASE_URL\"" in content
    assert "LOGIN_ENDPOINT" in content
    assert "urllib.request.urlopen" in content
    assert "def test_generated_login_case(case):" in content
    assert "SKIP_BY_DEFAULT = False" in content
    assert "NotImplementedError" not in content
    compile(content, "generated_login_api_adapter.py", "exec")


def test_pytest_export_rejects_unknown_adapter() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        PytestExportRequest.model_validate(
            {
                "cases": [CASE],
                "adapter": "unknown",
            }
        )


def test_pytest_export_rejects_invalid_env_name() -> None:
    with pytest.raises(ValueError, match="uppercase env var"):
        PytestExportRequest.model_validate(
            {
                "cases": [CASE],
                "target_base_url_env": "target-base-url",
            }
        )
