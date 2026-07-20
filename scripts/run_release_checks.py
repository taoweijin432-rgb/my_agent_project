import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGIN_RAG_ENV = {
    "EMBEDDING_PROVIDER": "hash",
    "CHROMA_PATH": "data/chroma-login-rag-eval",
    "CHROMA_COLLECTION": "login_rag_eval_hash",
}
DEFAULT_REFUND_RAG_ENV = {
    "EMBEDDING_PROVIDER": "hash",
    "CHROMA_PATH": "data/chroma-refund-rag-eval",
    "CHROMA_COLLECTION": "refund_rag_eval_hash",
}
DEFAULT_READINESS_ENV = {
    "DATABASE_BACKEND": "sqlite",
    "GENERATION_JOB_QUEUE_BACKEND": "in_memory",
    "GENERATION_HISTORY_DB_PATH": "/tmp/ai-testcase-generator-readiness/app.sqlite3",
    "CHROMA_PATH": "/tmp/ai-testcase-generator-readiness/chroma",
    "EMBEDDING_CACHE_DIR": "/tmp/ai-testcase-generator-readiness/model-cache",
}
DEFAULT_QUEUE_OBSERVABILITY_ENV = {
    "DATABASE_BACKEND": "sqlite",
    "GENERATION_JOB_QUEUE_BACKEND": "in_memory",
    "GENERATION_HISTORY_DB_PATH": "/tmp/ai-testcase-generator-queue-check/app.sqlite3",
}
DEFAULT_TEST_PLAN_EXECUTION_QUEUE_OBSERVABILITY_ENV = {
    "DATABASE_BACKEND": "sqlite",
    "GENERATION_JOB_QUEUE_BACKEND": "in_memory",
    "GENERATION_HISTORY_DB_PATH": (
        "/tmp/ai-testcase-generator-test-plan-execution-queue-check/app.sqlite3"
    ),
}
DEFAULT_TEST_AGENT_WORKFLOW_QUEUE_OBSERVABILITY_ENV = {
    "DATABASE_BACKEND": "sqlite",
    "GENERATION_JOB_QUEUE_BACKEND": "in_memory",
    "GENERATION_HISTORY_DB_PATH": (
        "/tmp/ai-testcase-generator-test-agent-workflow-queue-check/app.sqlite3"
    ),
}
DEFAULT_PYTEST_TARGETS = [
    "tests/test_agent_workflow.py",
    "tests/test_auth.py",
    "tests/test_auth_dependency.py",
    "tests/test_config.py",
    "tests/test_coverage_evaluation.py",
    "tests/test_deployment_templates.py",
    "tests/test_export.py",
    "tests/test_generate_api.py",
    "tests/test_generation_jobs.py",
    "tests/test_generation_job_store.py",
    "tests/test_generator.py",
    "tests/test_history.py",
    "tests/test_knowledge_api.py",
    "tests/test_metrics.py",
    "tests/test_middleware.py",
    "tests/test_middleware_logging.py",
    "tests/test_monitoring_docs.py",
    "tests/test_monitoring_metrics_check.py",
    "tests/test_monitoring_rollout_check.py",
    "tests/test_monitoring_stack_smoke.py",
    "tests/test_prompt.py",
    "tests/test_pytest_export.py",
    "tests/test_quality.py",
    "tests/test_queue_alerts.py",
    "tests/test_queue_alert_samples.py",
    "tests/test_reviewer.py",
    "tests/test_runtime_paths.py",
    "tests/test_queue_observability.py",
    "tests/test_rag_evaluation.py",
    "tests/test_readiness.py",
    "tests/test_recovery_smoke.py",
    "tests/test_release_checks.py",
    "tests/test_runtime_dependency_outage_smoke.py",
    "tests/test_rq_mysql_worker_stability_smoke.py",
    "tests/test_secret_scan.py",
    "tests/test_service_mode_calibration.py",
    "tests/test_service_mode_dependency_jitter_smoke.py",
    "tests/test_service_mode_workflow_load_smoke.py",
    "tests/test_test_agent_workflow_rq_mysql_smoke.py",
    "tests/test_test_agent_workflow.py",
    "tests/test_test_execution_smoke.py",
    "tests/test_test_execution_evaluation.py",
    "tests/test_test_agent_workflow_evaluation.py",
    "tests/test_test_agent_workflow_jobs.py",
    "tests/test_test_agent_workflow_queue_observability.py",
    "tests/test_test_agent_workflow_store.py",
    "tests/test_test_plan_api.py",
    "tests/test_test_plan_evaluation.py",
    "tests/test_test_plan_execution_queue_observability.py",
    "tests/test_test_plan_execution_jobs.py",
    "tests/test_test_plan_execution_runtime_smoke.py",
    "tests/test_test_plan_execution_store.py",
    "tests/test_test_plan_execution_worker_smoke.py",
    "tests/test_test_plan_generator.py",
    "tests/test_test_plan_models.py",
    "tests/test_test_report.py",
    "tests/test_test_report_evaluation.py",
    "tests/test_tool_adapters.py",
    "tests/test_tool_artifacts.py",
    "tests/test_tool_execution.py",
    "tests/test_ingest_documents.py",
]
DEFAULT_TYPE_CHECK_TARGETS = [
    "app/models/test_plan.py",
    "app/services/tool_adapters.py",
    "app/services/tool_artifacts.py",
    "app/services/tool_execution.py",
    "app/services/test_report.py",
    "app/services/test_plan_execution.py",
    "app/services/test_agent_workflow.py",
    "app/services/test_agent_workflow_jobs.py",
    "app/services/test_agent_workflow_metrics.py",
    "app/services/test_agent_workflow_store.py",
    "app/services/test_plan_execution_jobs.py",
    "app/services/test_plan_execution_store.py",
    "app/workers/test_agent_workflow_rq.py",
    "app/workers/test_plan_execution_rq.py",
]


@dataclass(frozen=True)
class CheckCommand:
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)


def main() -> None:
    args = parse_args()
    commands = build_default_commands(args)
    failed = False

    for check in commands:
        if not run_check(check, dry_run=args.dry_run):
            failed = True
            if args.fail_fast:
                raise SystemExit(1)

    if args.include_llm_smoke:
        if not run_llm_smoke(args):
            failed = True

    if failed:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local release checks for the AI test case generator.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for checks. Defaults to current interpreter.",
    )
    parser.add_argument(
        "--skip-rag-eval",
        action="store_true",
        help="Skip isolated login RAG ingest/evaluation.",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip pytest regression checks.",
    )
    parser.add_argument(
        "--skip-test-plan-eval",
        action="store_true",
        help="Skip deterministic test plan evaluation.",
    )
    parser.add_argument(
        "--skip-test-report-eval",
        action="store_true",
        help="Skip deterministic test execution report evaluation.",
    )
    parser.add_argument(
        "--skip-test-execution-eval",
        action="store_true",
        help="Skip deterministic end-to-end test execution evaluation.",
    )
    parser.add_argument(
        "--skip-test-agent-workflow-eval",
        action="store_true",
        help="Skip deterministic requirements-to-report workflow evaluation.",
    )
    parser.add_argument(
        "--skip-type-check",
        action="store_true",
        help="Skip mypy checks for test-agent contract modules.",
    )
    parser.add_argument(
        "--skip-recovery-smoke",
        action="store_true",
        help="Skip stale job recovery and test-plan execution worker smoke.",
    )
    parser.add_argument(
        "--skip-readiness-check",
        action="store_true",
        help="Skip runtime readiness check.",
    )
    parser.add_argument(
        "--skip-monitoring-check",
        action="store_true",
        help="Skip local monitoring metrics/alert template check.",
    )
    parser.add_argument(
        "--skip-queue-check",
        action="store_true",
        help="Skip queue/database observability checks.",
    )
    parser.add_argument(
        "--skip-diff-check",
        action="store_true",
        help="Skip `git diff --check`.",
    )
    parser.add_argument(
        "--skip-secret-scan",
        action="store_true",
        help="Skip local committed secret scanning.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed check.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print checks without executing them.",
    )
    parser.add_argument(
        "--include-llm-smoke",
        action="store_true",
        help="Run optional real FastAPI + RAG + LLM strong-gate smoke.",
    )
    parser.add_argument(
        "--include-llm-test-plan-eval",
        action="store_true",
        help="Run optional real LLM test-plan evaluation without deterministic fallback.",
    )
    parser.add_argument(
        "--include-llm-workflow-eval",
        action="store_true",
        help="Run optional real LLM requirements-to-report workflow evaluation.",
    )
    parser.add_argument(
        "--include-llm-workflow-benchmark",
        action="store_true",
        help="Run optional real LLM workflow latency benchmark.",
    )
    parser.add_argument(
        "--include-runtime-outage-smoke",
        action="store_true",
        help="Run optional Docker Redis/MySQL outage recovery smoke.",
    )
    parser.add_argument(
        "--include-rq-mysql-worker-stability-smoke",
        action="store_true",
        help="Run optional Docker Redis/RQ + MySQL worker stability smoke.",
    )
    parser.add_argument(
        "--include-test-agent-workflow-rq-mysql-smoke",
        action="store_true",
        help="Run optional Docker Redis/RQ + MySQL test Agent workflow smoke.",
    )
    parser.add_argument(
        "--include-queue-alert-check",
        action="store_true",
        help="Run optional queue metrics/alert threshold check.",
    )
    parser.add_argument(
        "--include-monitoring-stack-smoke",
        action="store_true",
        help="Run optional local Prometheus/Alertmanager stack smoke.",
    )
    parser.add_argument(
        "--include-monitoring-rollout-check",
        action="store_true",
        help="Run optional production/pre-production monitoring rollout evidence check.",
    )
    parser.add_argument(
        "--monitoring-rollout-evidence-path",
        default="data/ops-drills/monitoring-rollout-evidence.json",
        help="Evidence JSON path for --include-monitoring-rollout-check.",
    )
    parser.add_argument("--llm-port", type=int, default=8028)
    parser.add_argument("--llm-timeout", type=int, default=240)
    parser.add_argument("--api-key", default="release-check-key")
    return parser.parse_args()


def build_default_commands(args: argparse.Namespace) -> list[CheckCommand]:
    commands: list[CheckCommand] = []
    if not args.skip_rag_eval:
        commands.extend(
            [
                CheckCommand(
                    name="login-rag-ingest",
                    command=[
                        args.python,
                        "scripts/ingest_documents.py",
                        "knowledge/prd/login",
                        "knowledge/api/login",
                        "knowledge/security/login",
                        "knowledge/audit/login",
                        "--recursive",
                        "--reset",
                        "--chunk-size",
                        "900",
                    ],
                    env=DEFAULT_LOGIN_RAG_ENV,
                ),
                CheckCommand(
                    name="refund-rag-ingest",
                    command=[
                        args.python,
                        "scripts/ingest_documents.py",
                        "knowledge/prd/refund",
                        "knowledge/api/refund",
                        "knowledge/risk/refund",
                        "knowledge/audit/refund",
                        "--recursive",
                        "--reset",
                        "--chunk-size",
                        "900",
                    ],
                    env=DEFAULT_REFUND_RAG_ENV,
                ),
                CheckCommand(
                    name="login-rag-eval",
                    command=[
                        args.python,
                        "scripts/evaluate_rag.py",
                        "--cases",
                        "tests/fixtures/login_rag_eval_cases.json",
                        "--top-k",
                        "5",
                        "--case-keyword-ratio",
                        "1.0",
                        "--fail-under-source-hit-rate",
                        "1.0",
                        "--fail-under-keyword-hit-rate",
                        "1.0",
                    ],
                    env=DEFAULT_LOGIN_RAG_ENV,
                ),
                CheckCommand(
                    name="refund-rag-eval",
                    command=[
                        args.python,
                        "scripts/evaluate_rag.py",
                        "--cases",
                        "tests/fixtures/refund_rag_eval_cases.json",
                        "--top-k",
                        "5",
                        "--case-keyword-ratio",
                        "1.0",
                        "--fail-under-source-hit-rate",
                        "1.0",
                        "--fail-under-keyword-hit-rate",
                        "1.0",
                    ],
                    env=DEFAULT_REFUND_RAG_ENV,
                ),
            ]
        )
    if not args.skip_pytest:
        commands.append(
            CheckCommand(
                name="pytest-core",
                command=[args.python, "-m", "pytest", *DEFAULT_PYTEST_TARGETS, "-q"],
            )
        )
    if not args.skip_type_check:
        commands.append(
            CheckCommand(
                name="type-check-test-agent",
                command=[args.python, "-m", "mypy", *DEFAULT_TYPE_CHECK_TARGETS],
            )
        )
    if not args.skip_test_plan_eval:
        commands.append(
            CheckCommand(
                name="test-plan-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_plan.py",
                    "--json",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-tool-hit-rate",
                    "1.0",
                    "--fail-under-test-type-hit-rate",
                    "1.0",
                    "--fail-under-risk-keyword-hit-rate",
                    "1.0",
                ],
            )
        )
    if args.include_llm_test_plan_eval:
        commands.append(
            CheckCommand(
                name="llm-test-plan-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_plan.py",
                    "--json",
                    "--use-llm",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-tool-hit-rate",
                    "1.0",
                    "--fail-under-test-type-hit-rate",
                    "1.0",
                    "--fail-under-risk-keyword-hit-rate",
                    "1.0",
                ],
            )
        )
    if not args.skip_test_report_eval:
        commands.append(
            CheckCommand(
                name="test-report-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_report.py",
                    "--json",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-status-match-rate",
                    "1.0",
                    "--fail-under-summary-fact-quality-rate",
                    "1.0",
                    "--fail-under-coverage-match-rate",
                    "1.0",
                    "--fail-under-defect-grounding-rate",
                    "1.0",
                    "--fail-under-reason-classification-rate",
                    "1.0",
                    "--fail-under-reason-aware-recommendation-rate",
                    "1.0",
                    "--fail-under-recommendation-grounding-rate",
                    "1.0",
                    "--fail-under-next-action-quality-rate",
                    "1.0",
                    "--fail-under-evidence-artifact-quality-rate",
                    "1.0",
                    "--fail-under-export-fact-rate",
                    "1.0",
                ],
            )
        )
    if not args.skip_test_execution_eval:
        commands.append(
            CheckCommand(
                name="test-execution-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_execution.py",
                    "--json",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-report-status-rate",
                    "1.0",
                    "--fail-under-summary-fact-quality-rate",
                    "1.0",
                    "--fail-under-tool-status-rate",
                    "1.0",
                    "--fail-under-coverage-match-rate",
                    "1.0",
                    "--fail-under-defect-grounding-rate",
                    "1.0",
                    "--fail-under-blocked-grounding-rate",
                    "1.0",
                    "--fail-under-evidence-rate",
                    "1.0",
                ],
            )
        )
    if not args.skip_test_agent_workflow_eval:
        commands.append(
            CheckCommand(
                name="test-agent-workflow-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_agent_workflow.py",
                    "--json",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-tool-args-schema-rate",
                    "1.0",
                    "--fail-under-plan-tool-hit-rate",
                    "1.0",
                    "--fail-under-plan-test-type-hit-rate",
                    "1.0",
                    "--fail-under-plan-step-count-rate",
                    "1.0",
                    "--fail-under-risk-keyword-hit-rate",
                    "1.0",
                    "--fail-under-report-status-rate",
                    "1.0",
                    "--fail-under-summary-fact-quality-rate",
                    "1.0",
                    "--fail-under-tool-status-rate",
                    "1.0",
                    "--fail-under-coverage-match-rate",
                    "1.0",
                    "--fail-under-defect-grounding-rate",
                    "1.0",
                    "--fail-under-reason-classification-rate",
                    "1.0",
                    "--fail-under-reason-aware-recommendation-rate",
                    "1.0",
                    "--fail-under-recommendation-grounding-rate",
                    "1.0",
                    "--fail-under-next-action-quality-rate",
                    "1.0",
                    "--fail-under-evidence-artifact-quality-rate",
                    "1.0",
                    "--fail-under-evidence-rate",
                    "1.0",
                ],
            )
        )
    if args.include_llm_workflow_eval:
        commands.append(
            CheckCommand(
                name="llm-test-agent-workflow-eval",
                command=[
                    args.python,
                    "scripts/evaluate_test_agent_workflow.py",
                    "--json",
                    "--use-llm",
                    "--concurrency",
                    "1",
                    "--case-delay-seconds",
                    "2",
                    "--strict-plan-tools",
                    "--strict-plan-test-types",
                    "--strict-http-headers",
                    "--fail-under-case-pass-rate",
                    "1.0",
                    "--fail-under-tool-args-schema-rate",
                    "1.0",
                    "--fail-under-plan-tool-hit-rate",
                    "1.0",
                    "--fail-under-plan-test-type-hit-rate",
                    "1.0",
                    "--fail-under-plan-step-count-rate",
                    "1.0",
                    "--fail-under-risk-keyword-hit-rate",
                    "1.0",
                    "--fail-under-report-status-rate",
                    "1.0",
                    "--fail-under-summary-fact-quality-rate",
                    "1.0",
                    "--fail-under-tool-status-rate",
                    "1.0",
                    "--fail-under-coverage-match-rate",
                    "1.0",
                    "--fail-under-defect-grounding-rate",
                    "1.0",
                    "--fail-under-reason-classification-rate",
                    "1.0",
                    "--fail-under-reason-aware-recommendation-rate",
                    "1.0",
                    "--fail-under-recommendation-grounding-rate",
                    "1.0",
                    "--fail-under-next-action-quality-rate",
                    "1.0",
                    "--fail-under-evidence-artifact-quality-rate",
                    "1.0",
                    "--fail-under-evidence-rate",
                    "1.0",
                    "--fail-under-http-header-value-rate",
                    "1.0",
                ],
            )
        )
    if args.include_llm_workflow_benchmark:
        commands.append(
            CheckCommand(
                name="llm-test-agent-workflow-benchmark",
                command=[
                    args.python,
                    "scripts/evaluate_test_agent_workflow.py",
                    "--json",
                    "--use-llm",
                    "--concurrency",
                    "1",
                    "--case-delay-seconds",
                    "2",
                    "--fail-over-total-ms",
                    "240000",
                    "--fail-over-plan-generation-ms",
                    "180000",
                    "--benchmark-history-jsonl",
                    "data/llm-workflow-benchmark-history.jsonl",
                ],
            )
        )
    if not args.skip_recovery_smoke:
        commands.extend(
            [
                CheckCommand(
                    name="generation-recovery-smoke",
                    command=[
                        args.python,
                        "scripts/smoke_recover_stale_generation_jobs.py",
                        "--json",
                    ],
                ),
                CheckCommand(
                    name="test-plan-execution-worker-smoke",
                    command=[
                        args.python,
                        "scripts/smoke_test_plan_execution_worker.py",
                        "--json",
                    ],
                ),
                CheckCommand(
                    name="test-plan-execution-runtime-smoke",
                    command=[
                        args.python,
                        "scripts/smoke_test_plan_execution_runtime.py",
                        "--json",
                    ],
                ),
            ]
        )
    if args.include_runtime_outage_smoke:
        commands.append(
            CheckCommand(
                name="runtime-dependency-outage-smoke",
                command=[
                    args.python,
                    "scripts/smoke_runtime_dependency_outage.py",
                    "--json",
                ],
            )
        )
    if args.include_rq_mysql_worker_stability_smoke:
        commands.append(
            CheckCommand(
                name="rq-mysql-worker-stability-smoke",
                command=[
                    args.python,
                    "scripts/smoke_rq_mysql_worker_stability.py",
                    "--json",
                ],
            )
        )
    if args.include_test_agent_workflow_rq_mysql_smoke:
        commands.append(
            CheckCommand(
                name="test-agent-workflow-rq-mysql-smoke",
                command=[
                    args.python,
                    "scripts/smoke_test_agent_workflow_rq_mysql.py",
                    "--json",
                ],
            )
        )
    if args.include_queue_alert_check:
        commands.append(
            CheckCommand(
                name="queue-alert-check",
                command=[
                    args.python,
                    "scripts/check_queue_alerts.py",
                    "--json",
                ],
            )
        )
    if args.include_monitoring_stack_smoke:
        commands.append(
            CheckCommand(
                name="monitoring-stack-smoke",
                command=[
                    args.python,
                    "scripts/smoke_monitoring_stack.py",
                    "--json",
                ],
            )
        )
    if args.include_monitoring_rollout_check:
        commands.append(
            CheckCommand(
                name="monitoring-rollout-check",
                command=[
                    args.python,
                    "scripts/check_monitoring_rollout.py",
                    "--evidence-path",
                    args.monitoring_rollout_evidence_path,
                    "--json",
                ],
            )
        )
    if not args.skip_monitoring_check:
        commands.append(
            CheckCommand(
                name="monitoring-metrics-check",
                command=[
                    args.python,
                    "scripts/check_monitoring_metrics.py",
                    "--json",
                ],
            )
        )
    if not args.skip_readiness_check:
        commands.append(
            CheckCommand(
                name="readiness-check",
                command=[
                    args.python,
                    "scripts/check_readiness.py",
                    "--json",
                ],
                env=DEFAULT_READINESS_ENV,
            )
        )
    if not args.skip_queue_check:
        commands.extend(
            [
                CheckCommand(
                    name="generation-queue-check",
                    command=[
                        args.python,
                        "scripts/check_generation_queue.py",
                        "--json",
                        "--fail-on-mismatch",
                    ],
                    env=DEFAULT_QUEUE_OBSERVABILITY_ENV,
                ),
                CheckCommand(
                    name="test-plan-execution-queue-check",
                    command=[
                        args.python,
                        "scripts/check_test_plan_execution_queue.py",
                        "--json",
                        "--fail-on-mismatch",
                    ],
                    env=DEFAULT_TEST_PLAN_EXECUTION_QUEUE_OBSERVABILITY_ENV,
                ),
                CheckCommand(
                    name="test-agent-workflow-queue-check",
                    command=[
                        args.python,
                        "scripts/check_test_agent_workflow_queue.py",
                        "--json",
                        "--fail-on-mismatch",
                    ],
                    env=DEFAULT_TEST_AGENT_WORKFLOW_QUEUE_OBSERVABILITY_ENV,
                ),
            ]
        )
    if not args.skip_secret_scan:
        commands.append(
            CheckCommand(
                name="secret-scan",
                command=[
                    args.python,
                    "scripts/check_secrets.py",
                    "--json",
                ],
            )
        )
    if not args.skip_diff_check:
        commands.append(
            CheckCommand(
                name="git-diff-check",
                command=["git", "diff", "--check"],
            )
        )
    return commands


def run_check(check: CheckCommand, *, dry_run: bool = False) -> bool:
    print(f"\n==> {check.name}")
    print(format_command(check.command, env=check.env))
    if dry_run:
        return True

    env = os.environ.copy()
    env.update(check.env)
    result = subprocess.run(check.command, cwd=PROJECT_ROOT, env=env, check=False)
    if result.returncode == 0:
        print(f"PASS {check.name}")
        return True
    print(f"FAIL {check.name}: exit={result.returncode}")
    return False


def run_llm_smoke(args: argparse.Namespace) -> bool:
    if args.dry_run:
        print("\n==> llm-strong-gate-smoke")
        print("Would start uvicorn and run 409/200 strong-gate smoke.")
        return True

    env = os.environ.copy()
    env.update(DEFAULT_LOGIN_RAG_ENV)
    env.update(
        {
            "APP_ENV": "development",
            "APP_API_KEY": args.api_key,
            "DATABASE_BACKEND": "sqlite",
            "GENERATION_HISTORY_DB_PATH": "data/release-check-smoke.sqlite3",
            "GENERATION_JOB_QUEUE_BACKEND": "in_memory",
            "RATE_LIMIT_ENABLED": "false",
            "REQUEST_LOG_ENABLED": "false",
            "LLM_TIMEOUT_SECONDS": str(args.llm_timeout),
            "LLM_MAX_RETRIES": "1",
            "AGENT_REVIEW_RETRY_ENABLED": "true",
            "AGENT_REVIEW_REQUIRE_PASS": "true",
        }
    )

    print("\n==> llm-strong-gate-smoke")
    server = subprocess.Popen(
        [
            args.python,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.llm_port),
        ],
        cwd=PROJECT_ROOT,
        env=env,
    )
    try:
        wait_for_health(args.llm_port, timeout_seconds=30)
        fail_response = post_json(
            args.llm_port,
            "/api/v1/test-cases/generate",
            api_key=args.api_key,
            payload=small_capacity_payload(),
            timeout_seconds=args.llm_timeout * 2,
        )
        if fail_response["status"] != 409:
            print(f"FAIL llm-strong-gate-smoke: expected 409, got {fail_response['status']}")
            return False
        fail_detail = fail_response["body"].get("detail", {})
        if fail_detail.get("code") != "quality_gate_failed":
            print(f"FAIL llm-strong-gate-smoke: unexpected failure detail {fail_detail}")
            return False

        pass_response = post_json(
            args.llm_port,
            "/api/v1/test-cases/generate",
            api_key=args.api_key,
            payload=full_capacity_payload(),
            timeout_seconds=args.llm_timeout * 3,
        )
        if pass_response["status"] != 200:
            print(f"FAIL llm-strong-gate-smoke: expected 200, got {pass_response['status']}")
            return False
        body = pass_response["body"]
        review = body.get("metadata", {}).get("review") or {}
        if not review.get("passed"):
            print(f"FAIL llm-strong-gate-smoke: review did not pass {review}")
            return False
        print(
            "PASS llm-strong-gate-smoke: "
            f"409 quality_gate_failed, 200 review_score={review.get('score')}"
        )
        return True
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


def wait_for_health(port: int, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health",
                timeout=2,
            )
            if response.status == 200:
                return
        except Exception as exc:  # pragma: no cover - defensive around server startup
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Server did not become healthy: {last_error}")


def post_json(
    port: int,
    path: str,
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
        body = json.loads(response.read().decode("utf-8"))
        return {"status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return {"status": exc.code, "body": body}


def small_capacity_payload() -> dict[str, Any]:
    return {
        "description": (
            "请基于登录知识库生成测试用例，必须覆盖 disabled、deleted、SQL 注入、"
            "暴力破解、账号枚举、token 泄露、审计日志字段。"
        ),
        "max_cases": 3,
        "knowledge_top_k": 5,
        "include_context": False,
        "focus_types": ["functional", "exception", "security"],
    }


def full_capacity_payload() -> dict[str, Any]:
    return {
        "description": (
            "请基于登录知识库和原子验收矩阵生成完整测试用例。必须逐项覆盖 "
            "active、disabled、deleted、密码长度 7/8/32/33 位、连续 5 次错误锁定 "
            "15 分钟、锁定期间正确密码失败、验证码错误不累计密码错误次数、连续 "
            "3 次错误触发二次短信验证码、access_token 2 小时、refresh_token 7 天、"
            "管理员权限、普通用户权限、SQL 注入、暴力破解、账号枚举、token 泄露、"
            "审计日志字段。"
        ),
        "max_cases": 20,
        "knowledge_top_k": 5,
        "include_context": False,
        "focus_types": ["functional", "boundary", "exception", "permission", "security"],
    }


def format_command(command: list[str], *, env: dict[str, str]) -> str:
    prefix = " ".join(f"{key}={value}" for key, value in sorted(env.items()))
    rendered = " ".join(command)
    return f"{prefix} {rendered}".strip()


if __name__ == "__main__":
    main()
