import subprocess
from pathlib import Path

import httpx

from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRunStatus
from app.services.tool_adapters import HTTPToolAdapter, PytestToolAdapter
from app.services.tool_artifacts import ToolArtifactStore


def _step(**tool_args) -> PlanStep:
    return PlanStep(
        id="TP-001",
        title="验证创建退款",
        objective="调用创建退款接口",
        tool=ToolType.http,
        tool_args=tool_args,
    )


def test_http_tool_adapter_marks_expected_status_as_passed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/refunds"
        assert request.headers["x-test"] == "yes"
        return httpx.Response(201, json={"id": "refund-1"})

    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.run(
        _step(
            method="POST",
            path="/api/v1/refunds",
            headers={"X-Test": "yes"},
            json={"idempotency_key": "k-1"},
            expected_status=[200, 201],
        )
    )

    assert result.status == ToolRunStatus.passed
    assert result.exit_code == 0
    assert result.command == ["POST", "/api/v1/refunds"]
    assert "returned 201" in result.output_summary


def test_http_tool_adapter_writes_response_artifact(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})),
        artifact_store=store,
    )

    result = adapter.run(_step(path="/api/v1/refunds"))

    assert len(result.artifact_paths) == 1
    content = (tmp_path / result.artifact_paths[0]).read_text(encoding="utf-8")
    assert "GET /api/v1/refunds" in content
    assert "status=200" in content
    assert '{"ok":true}' in content


def test_http_tool_adapter_marks_unexpected_status_as_failed() -> None:
    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    result = adapter.run(_step(path="/api/v1/refunds", expected_status=200))

    assert result.status == ToolRunStatus.failed
    assert result.exit_code == 1
    assert "expected [200]" in result.output_summary


def test_http_tool_adapter_marks_network_error_as_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.run(_step(path="/api/v1/refunds"))

    assert result.status == ToolRunStatus.blocked
    assert result.exit_code is None
    assert "connection refused" in result.output_summary


def test_http_tool_adapter_rejects_external_url() -> None:
    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
    )

    result = adapter.run(_step(path="https://example.com/api"))

    assert result.status == ToolRunStatus.blocked
    assert result.command == []
    assert "must be relative to base_url" in result.output_summary


def test_http_tool_adapter_parses_method_from_endpoint_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/refunds/refund-1"
        return httpx.Response(204)

    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.run(
        _step(endpoint_hint="DELETE /api/v1/refunds/refund-1", expected_status=204)
    )

    assert result.status == ToolRunStatus.passed
    assert result.command == ["DELETE", "/api/v1/refunds/refund-1"]


def test_pytest_tool_adapter_marks_zero_exit_as_passed() -> None:
    calls = []

    def runner(command: list[str], timeout_seconds: float):
        calls.append((command, timeout_seconds))
        return subprocess.CompletedProcess(command, 0, stdout="1 passed", stderr="")

    adapter = PytestToolAdapter(timeout_seconds=12, runner=runner)

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={
                "test_path": "tests/test_tool_adapters.py",
                "keyword": "http_tool",
                "maxfail": 2,
            },
        )
    )

    assert result.status == ToolRunStatus.passed
    assert result.exit_code == 0
    assert "--maxfail" in result.command
    assert "2" in result.command
    assert "-k" in result.command
    assert "http_tool" in result.command
    assert calls[0][1] == 12
    assert "1 passed" in result.output_summary


def test_pytest_tool_adapter_writes_output_artifact(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    adapter = PytestToolAdapter(
        artifact_store=store,
        runner=lambda command, _: subprocess.CompletedProcess(
            command,
            0,
            stdout="1 passed",
            stderr="",
        ),
    )

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={"test_path": "tests/test_tool_adapters.py"},
        )
    )

    assert len(result.artifact_paths) == 1
    content = (tmp_path / result.artifact_paths[0]).read_text(encoding="utf-8")
    assert "exit_code=0" in content
    assert "1 passed" in content


def test_pytest_tool_adapter_marks_nonzero_exit_as_failed() -> None:
    adapter = PytestToolAdapter(
        runner=lambda command, _: subprocess.CompletedProcess(
            command,
            1,
            stdout="1 failed",
            stderr="",
        )
    )

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={"test_path": "tests/test_tool_adapters.py"},
        )
    )

    assert result.status == ToolRunStatus.failed
    assert result.exit_code == 1
    assert "1 failed" in result.output_summary


def test_pytest_tool_adapter_rejects_unsafe_path() -> None:
    adapter = PytestToolAdapter()

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={"test_path": "../secrets.py"},
        )
    )

    assert result.status == ToolRunStatus.blocked
    assert result.command == []
    assert "safe relative path" in result.output_summary


def test_pytest_tool_adapter_rejects_path_outside_allowlist() -> None:
    adapter = PytestToolAdapter(allowed_paths=("generated_tests",))

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={"test_path": "tests/test_tool_adapters.py"},
        )
    )

    assert result.status == ToolRunStatus.blocked
    assert "allowed paths: generated_tests" in result.output_summary


def test_pytest_tool_adapter_marks_timeout_as_blocked() -> None:
    def runner(command: list[str], timeout_seconds: float):
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    adapter = PytestToolAdapter(timeout_seconds=1, runner=runner)

    result = adapter.run(
        PlanStep(
            id="TP-001",
            title="运行 pytest",
            objective="运行指定测试",
            tool=ToolType.pytest,
            tool_args={"test_path": "tests/test_tool_adapters.py"},
        )
    )

    assert result.status == ToolRunStatus.blocked
    assert result.exit_code is None
    assert "TimeoutExpired" in result.output_summary
