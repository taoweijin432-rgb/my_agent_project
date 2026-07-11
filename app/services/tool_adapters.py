import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT
from app.models.test_plan import (
    HTTPToolArgs,
    PytestToolArgs,
    TestPlanStep,
    TestToolType,
    ToolRun,
    ToolRunStatus,
)
from app.services.tool_artifacts import ToolArtifactStore


class ToolAdapterValidationError(ValueError):
    pass


PytestRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


class HTTPToolAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        artifact_store: ToolArtifactStore | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.artifact_store = artifact_store

    def run(self, step: TestPlanStep) -> ToolRun:
        started_at = _utc_now()
        try:
            args = _http_args_from_step(step)
            response = self._send(args)
            expected_statuses = args.expected_statuses
            passed = response.status_code in expected_statuses
            artifact_paths = _http_artifacts(
                self.artifact_store,
                step,
                args,
                response,
            )
            return _tool_run(
                step,
                status=ToolRunStatus.passed if passed else ToolRunStatus.failed,
                started_at=started_at,
                tool=TestToolType.http,
                command=_http_command_from_step(step),
                exit_code=0 if passed else 1,
                artifact_paths=artifact_paths,
                output_summary=(
                    f"{args.resolved_method} {args.resolved_path} returned "
                    f"{response.status_code}; expected {sorted(expected_statuses)}."
                ),
            )
        except (ToolAdapterValidationError, httpx.HTTPError) as exc:
            return _tool_run(
                step,
                status=ToolRunStatus.blocked,
                started_at=started_at,
                tool=TestToolType.http,
                command=_http_command_from_step(step),
                exit_code=None,
                output_summary=f"HTTP tool blocked: {type(exc).__name__}: {exc}",
            )

    def _send(self, args: HTTPToolArgs) -> httpx.Response:
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            return client.request(
                args.resolved_method,
                args.resolved_path,
                headers=args.headers,
                json=args.json_body,
            )


class PytestToolAdapter:
    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        python_executable: str = sys.executable,
        timeout_seconds: float = 60.0,
        allowed_paths: list[str] | tuple[str, ...] = ("tests",),
        artifact_store: ToolArtifactStore | None = None,
        runner: PytestRunner | None = None,
    ):
        self.project_root = project_root.resolve()
        self.python_executable = python_executable
        self.timeout_seconds = timeout_seconds
        self.allowed_paths = tuple(path.strip().strip("/") for path in allowed_paths if path.strip())
        self.artifact_store = artifact_store
        self.runner = runner or self._run_command

    def run(self, step: TestPlanStep) -> ToolRun:
        started_at = _utc_now()
        command: list[str] = []
        try:
            command = _pytest_command_from_step(
                step,
                project_root=self.project_root,
                python_executable=self.python_executable,
                allowed_paths=self.allowed_paths,
            )
            result = self.runner(command, self.timeout_seconds)
            passed = result.returncode == 0
            artifact_paths = _pytest_artifacts(self.artifact_store, step, result)
            return _tool_run(
                step,
                status=ToolRunStatus.passed if passed else ToolRunStatus.failed,
                started_at=started_at,
                tool=TestToolType.pytest,
                command=command,
                exit_code=result.returncode,
                artifact_paths=artifact_paths,
                output_summary=_pytest_summary(result),
            )
        except (ToolAdapterValidationError, subprocess.SubprocessError, OSError) as exc:
            return _tool_run(
                step,
                status=ToolRunStatus.blocked,
                started_at=started_at,
                tool=TestToolType.pytest,
                command=command,
                exit_code=None,
                output_summary=f"pytest tool blocked: {type(exc).__name__}: {exc}",
            )

    def _run_command(
        self,
        command: list[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.project_root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )


def _http_args_from_step(step: TestPlanStep) -> HTTPToolArgs:
    if step.tool != TestToolType.http:
        raise ToolAdapterValidationError("HTTPToolAdapter only accepts http steps.")

    try:
        return HTTPToolArgs.model_validate(step.tool_args)
    except ValidationError as exc:
        raise ToolAdapterValidationError(str(exc)) from exc


def _tool_run(
    step: TestPlanStep,
    *,
    status: ToolRunStatus,
    started_at: str,
    tool: TestToolType,
    command: list[str],
    exit_code: int | None,
    artifact_paths: list[str] | None = None,
    output_summary: str,
) -> ToolRun:
    return ToolRun(
        id=f"run-{uuid4().hex[:12]}",
        plan_step_id=step.id,
        tool=tool,
        status=status,
        command=command,
        started_at=started_at,
        finished_at=_utc_now(),
        exit_code=exit_code,
        artifact_paths=artifact_paths or [],
        output_summary=output_summary,
    )


def _http_command_from_step(step: TestPlanStep) -> list[str]:
    try:
        args = _http_args_from_step(step)
    except ToolAdapterValidationError:
        return []
    return [args.resolved_method, args.resolved_path]


def _pytest_command_from_step(
    step: TestPlanStep,
    *,
    project_root: Path,
    python_executable: str,
    allowed_paths: tuple[str, ...],
) -> list[str]:
    if step.tool != TestToolType.pytest:
        raise ToolAdapterValidationError("PytestToolAdapter only accepts pytest steps.")

    args = _pytest_args_from_step(step)
    test_path = _safe_pytest_path(
        args.resolved_test_path,
        project_root,
        allowed_paths,
    )
    command = [python_executable, "-m", "pytest", str(test_path), "-q"]

    command.extend(["--maxfail", str(args.maxfail)])

    if args.keyword:
        command.extend(["-k", args.keyword])

    if args.marker:
        command.extend(["-m", args.marker])

    return command


def _pytest_args_from_step(step: TestPlanStep) -> PytestToolArgs:
    try:
        return PytestToolArgs.model_validate(step.tool_args)
    except ValidationError as exc:
        raise ToolAdapterValidationError(str(exc)) from exc


def _safe_pytest_path(
    value: Any,
    project_root: Path,
    allowed_paths: tuple[str, ...],
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ToolAdapterValidationError("pytest step requires test_path.")
    raw_path = Path(value.strip())
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ToolAdapterValidationError("test_path must be a safe relative path.")
    if not allowed_paths:
        raise ToolAdapterValidationError("No pytest allowed paths configured.")
    if not _is_under_allowed_path(raw_path, allowed_paths):
        allowed = ", ".join(allowed_paths)
        raise ToolAdapterValidationError(f"test_path must be under allowed paths: {allowed}.")
    test_path = (project_root / raw_path).resolve()
    if project_root not in test_path.parents and test_path != project_root:
        raise ToolAdapterValidationError("test_path escapes project root.")
    if not test_path.exists():
        raise ToolAdapterValidationError(f"test_path does not exist: {raw_path}")
    return raw_path


def _is_under_allowed_path(raw_path: Path, allowed_paths: tuple[str, ...]) -> bool:
    normalized = raw_path.as_posix()
    return any(
        normalized == allowed_path or normalized.startswith(f"{allowed_path}/")
        for allowed_path in allowed_paths
    )


def _pytest_summary(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if not output:
        return f"pytest exited with code {result.returncode}."
    return output[-1000:]


def _http_artifacts(
    artifact_store: ToolArtifactStore | None,
    step: TestPlanStep,
    args: HTTPToolArgs,
    response: httpx.Response,
) -> list[str]:
    if artifact_store is None:
        return []
    content = "\n".join(
        [
            f"{args.resolved_method} {args.resolved_path}",
            f"status={response.status_code}",
            "",
            "headers:",
            "\n".join(f"{key}: {value}" for key, value in response.headers.items()),
            "",
            "body:",
            response.text,
        ]
    )
    return [
        artifact_store.write_text(
            prefix=step.id,
            filename="http-response.txt",
            content=content,
        )
    ]


def _pytest_artifacts(
    artifact_store: ToolArtifactStore | None,
    step: TestPlanStep,
    result: subprocess.CompletedProcess[str],
) -> list[str]:
    if artifact_store is None:
        return []
    content = "\n".join(
        [
            f"exit_code={result.returncode}",
            "",
            "stdout:",
            result.stdout or "",
            "",
            "stderr:",
            result.stderr or "",
        ]
    )
    return [
        artifact_store.write_text(
            prefix=step.id,
            filename="pytest-output.txt",
            content=content,
        )
    ]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
