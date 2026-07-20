from argparse import Namespace

from scripts.run_release_checks import build_default_commands


def _args(**overrides):
    values = {
        "python": "python",
        "skip_rag_eval": False,
        "skip_pytest": False,
        "skip_test_plan_eval": False,
        "skip_test_report_eval": False,
        "skip_test_execution_eval": False,
        "skip_test_agent_workflow_eval": False,
        "skip_type_check": False,
        "skip_recovery_smoke": False,
        "skip_readiness_check": False,
        "skip_monitoring_check": False,
        "skip_queue_check": False,
        "skip_diff_check": False,
        "skip_secret_scan": False,
        "include_llm_test_plan_eval": False,
        "include_llm_workflow_eval": False,
        "include_llm_workflow_benchmark": False,
        "include_runtime_outage_smoke": False,
        "include_rq_mysql_worker_stability_smoke": False,
        "include_test_agent_workflow_rq_mysql_smoke": False,
        "include_queue_alert_check": False,
        "include_monitoring_stack_smoke": False,
        "include_monitoring_rollout_check": False,
        "monitoring_rollout_evidence_path": (
            "data/ops-drills/monitoring-rollout-evidence.json"
        ),
    }
    values.update(overrides)
    return Namespace(**values)


def test_release_checks_include_rag_pytest_and_diff_by_default() -> None:
    commands = build_default_commands(_args())

    names = [command.name for command in commands]

    assert names == [
        "login-rag-ingest",
        "refund-rag-ingest",
        "login-rag-eval",
        "refund-rag-eval",
        "pytest-core",
        "type-check-test-agent",
        "test-plan-eval",
        "test-report-eval",
        "test-execution-eval",
        "test-agent-workflow-eval",
        "generation-recovery-smoke",
        "test-plan-execution-worker-smoke",
        "test-plan-execution-runtime-smoke",
        "monitoring-metrics-check",
        "readiness-check",
        "generation-queue-check",
        "test-plan-execution-queue-check",
        "test-agent-workflow-queue-check",
        "secret-scan",
        "git-diff-check",
    ]
    assert commands[0].env["CHROMA_COLLECTION"] == "login_rag_eval_hash"
    assert commands[1].env["CHROMA_COLLECTION"] == "refund_rag_eval_hash"
    assert "tests/fixtures/login_rag_eval_cases.json" in commands[2].command
    assert "tests/fixtures/refund_rag_eval_cases.json" in commands[3].command
    assert "tests/test_generator.py" in commands[4].command
    assert "tests/test_generate_api.py" in commands[4].command
    assert "tests/test_middleware.py" in commands[4].command
    assert "tests/test_queue_alerts.py" in commands[4].command
    assert "tests/test_release_checks.py" in commands[4].command
    assert "tests/test_runtime_dependency_outage_smoke.py" in commands[4].command
    assert "tests/test_rq_mysql_worker_stability_smoke.py" in commands[4].command
    assert "tests/test_secret_scan.py" in commands[4].command
    assert "tests/test_test_agent_workflow_rq_mysql_smoke.py" in commands[4].command
    assert "tests/test_test_agent_workflow.py" in commands[4].command
    assert "tests/test_test_agent_workflow_evaluation.py" in commands[4].command
    assert "tests/test_test_agent_workflow_jobs.py" in commands[4].command
    assert "tests/test_test_agent_workflow_queue_observability.py" in commands[4].command
    assert "tests/test_test_agent_workflow_store.py" in commands[4].command
    assert "tests/test_monitoring_metrics_check.py" in commands[4].command
    assert "tests/test_monitoring_rollout_check.py" in commands[4].command
    assert "tests/test_monitoring_stack_smoke.py" in commands[4].command
    assert "app/models/test_plan.py" in commands[5].command
    assert "app/services/tool_adapters.py" in commands[5].command
    assert "app/services/tool_artifacts.py" in commands[5].command
    assert "app/services/test_agent_workflow.py" in commands[5].command
    assert "app/services/test_agent_workflow_jobs.py" in commands[5].command
    assert "app/services/test_agent_workflow_metrics.py" in commands[5].command
    assert "app/services/test_agent_workflow_store.py" in commands[5].command
    assert "app/services/test_plan_execution_jobs.py" in commands[5].command
    assert "app/workers/test_agent_workflow_rq.py" in commands[5].command
    assert "scripts/evaluate_test_plan.py" in commands[6].command
    assert "scripts/evaluate_test_report.py" in commands[7].command
    assert "--fail-under-summary-fact-quality-rate" in commands[7].command
    assert "--fail-under-reason-classification-rate" in commands[7].command
    assert "--fail-under-reason-aware-recommendation-rate" in commands[7].command
    assert "--fail-under-recommendation-grounding-rate" in commands[7].command
    assert "--fail-under-next-action-quality-rate" in commands[7].command
    assert "--fail-under-evidence-artifact-quality-rate" in commands[7].command
    assert "scripts/evaluate_test_execution.py" in commands[8].command
    assert "--fail-under-blocked-grounding-rate" in commands[8].command
    assert "scripts/evaluate_test_agent_workflow.py" in commands[9].command
    assert "--fail-under-tool-args-schema-rate" in commands[9].command
    assert "--fail-under-plan-tool-hit-rate" in commands[9].command
    assert "--fail-under-plan-test-type-hit-rate" in commands[9].command
    assert "--fail-under-summary-fact-quality-rate" in commands[9].command
    assert "--fail-under-reason-classification-rate" in commands[9].command
    assert "--fail-under-reason-aware-recommendation-rate" in commands[9].command
    assert "--fail-under-recommendation-grounding-rate" in commands[9].command
    assert "--fail-under-next-action-quality-rate" in commands[9].command
    assert "--fail-under-evidence-artifact-quality-rate" in commands[9].command
    assert "scripts/smoke_test_plan_execution_worker.py" in commands[11].command
    assert "scripts/smoke_test_plan_execution_runtime.py" in commands[12].command
    assert "scripts/check_monitoring_metrics.py" in commands[13].command
    assert commands[15].env["GENERATION_JOB_QUEUE_BACKEND"] == "in_memory"
    assert "scripts/check_generation_queue.py" in commands[15].command
    assert commands[16].env["GENERATION_JOB_QUEUE_BACKEND"] == "in_memory"
    assert "scripts/check_test_plan_execution_queue.py" in commands[16].command
    assert commands[17].env["GENERATION_JOB_QUEUE_BACKEND"] == "in_memory"
    assert "scripts/check_test_agent_workflow_queue.py" in commands[17].command
    assert "scripts/check_secrets.py" in commands[18].command


def test_release_checks_can_skip_expensive_sections() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=False,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_diff_check=False,
        )
    )

    assert [command.name for command in commands] == [
        "type-check-test-agent",
        "secret-scan",
        "git-diff-check",
    ]


def test_release_checks_can_skip_type_check() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_diff_check=False,
        )
    )

    assert [command.name for command in commands] == ["secret-scan", "git-diff-check"]


def test_release_checks_can_skip_secret_scan() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=False,
        )
    )

    assert [command.name for command in commands] == ["git-diff-check"]


def test_release_checks_can_include_real_llm_test_plan_eval() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_llm_test_plan_eval=True,
        )
    )

    assert [command.name for command in commands] == ["llm-test-plan-eval"]
    assert "scripts/evaluate_test_plan.py" in commands[0].command
    assert "--use-llm" in commands[0].command
    assert "--allow-fallback" not in commands[0].command


def test_release_checks_can_include_real_llm_workflow_eval() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_llm_workflow_eval=True,
        )
    )

    assert [command.name for command in commands] == ["llm-test-agent-workflow-eval"]
    assert "scripts/evaluate_test_agent_workflow.py" in commands[0].command
    assert "--use-llm" in commands[0].command
    assert "--concurrency" in commands[0].command
    assert "1" in commands[0].command
    assert "--case-delay-seconds" in commands[0].command
    assert "--strict-plan-tools" in commands[0].command
    assert "--strict-plan-test-types" in commands[0].command
    assert "--strict-http-headers" in commands[0].command
    assert "--fail-under-tool-args-schema-rate" in commands[0].command
    assert "--fail-under-http-header-value-rate" in commands[0].command
    assert "--fail-under-summary-fact-quality-rate" in commands[0].command
    assert "--fail-under-reason-classification-rate" in commands[0].command
    assert "--fail-under-reason-aware-recommendation-rate" in commands[0].command
    assert "--fail-under-recommendation-grounding-rate" in commands[0].command
    assert "--fail-under-next-action-quality-rate" in commands[0].command
    assert "--fail-under-evidence-artifact-quality-rate" in commands[0].command
    assert "--allow-fallback" not in commands[0].command


def test_release_checks_can_include_real_llm_workflow_benchmark() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_llm_workflow_benchmark=True,
        )
    )

    assert [command.name for command in commands] == [
        "llm-test-agent-workflow-benchmark"
    ]
    assert "scripts/evaluate_test_agent_workflow.py" in commands[0].command
    assert "--use-llm" in commands[0].command
    assert "--concurrency" in commands[0].command
    assert "1" in commands[0].command
    assert "--case-delay-seconds" in commands[0].command
    assert "--fail-over-total-ms" in commands[0].command
    assert "--fail-over-plan-generation-ms" in commands[0].command
    assert "--benchmark-history-jsonl" in commands[0].command
    assert "data/llm-workflow-benchmark-history.jsonl" in commands[0].command
    assert "--fail-under-case-pass-rate" not in commands[0].command


def test_release_checks_can_include_runtime_outage_smoke() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_runtime_outage_smoke=True,
        )
    )

    assert [command.name for command in commands] == [
        "runtime-dependency-outage-smoke"
    ]
    assert "scripts/smoke_runtime_dependency_outage.py" in commands[0].command


def test_release_checks_can_include_rq_mysql_worker_stability_smoke() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_rq_mysql_worker_stability_smoke=True,
        )
    )

    assert [command.name for command in commands] == [
        "rq-mysql-worker-stability-smoke"
    ]
    assert "scripts/smoke_rq_mysql_worker_stability.py" in commands[0].command


def test_release_checks_can_include_test_agent_workflow_rq_mysql_smoke() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_test_agent_workflow_rq_mysql_smoke=True,
        )
    )

    assert [command.name for command in commands] == [
        "test-agent-workflow-rq-mysql-smoke"
    ]
    assert "scripts/smoke_test_agent_workflow_rq_mysql.py" in commands[0].command


def test_release_checks_can_include_queue_alert_check() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_queue_alert_check=True,
        )
    )

    assert [command.name for command in commands] == ["queue-alert-check"]
    assert "scripts/check_queue_alerts.py" in commands[0].command


def test_release_checks_can_include_monitoring_stack_smoke() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_monitoring_stack_smoke=True,
        )
    )

    assert [command.name for command in commands] == ["monitoring-stack-smoke"]
    assert "scripts/smoke_monitoring_stack.py" in commands[0].command


def test_release_checks_can_include_monitoring_rollout_check() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
            include_monitoring_rollout_check=True,
            monitoring_rollout_evidence_path="data/ops-drills/prod-monitoring.json",
        )
    )

    assert [command.name for command in commands] == ["monitoring-rollout-check"]
    assert "scripts/check_monitoring_rollout.py" in commands[0].command
    assert "--evidence-path" in commands[0].command
    assert "data/ops-drills/prod-monitoring.json" in commands[0].command


def test_release_checks_can_skip_monitoring_metrics_check() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_test_report_eval=True,
            skip_test_execution_eval=True,
            skip_test_agent_workflow_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_monitoring_check=True,
            skip_queue_check=True,
            skip_secret_scan=True,
            skip_diff_check=True,
        )
    )

    assert commands == []
