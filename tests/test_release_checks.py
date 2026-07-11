from argparse import Namespace

from scripts.run_release_checks import build_default_commands


def _args(**overrides):
    values = {
        "python": "python",
        "skip_rag_eval": False,
        "skip_pytest": False,
        "skip_test_plan_eval": False,
        "skip_type_check": False,
        "skip_recovery_smoke": False,
        "skip_readiness_check": False,
        "skip_queue_check": False,
        "skip_diff_check": False,
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
        "generation-recovery-smoke",
        "readiness-check",
        "generation-queue-check",
        "git-diff-check",
    ]
    assert commands[0].env["CHROMA_COLLECTION"] == "login_rag_eval_hash"
    assert commands[1].env["CHROMA_COLLECTION"] == "refund_rag_eval_hash"
    assert "tests/fixtures/login_rag_eval_cases.json" in commands[2].command
    assert "tests/fixtures/refund_rag_eval_cases.json" in commands[3].command
    assert "tests/test_generator.py" in commands[4].command
    assert "tests/test_generate_api.py" in commands[4].command
    assert "tests/test_middleware.py" in commands[4].command
    assert "app/models/test_plan.py" in commands[5].command
    assert "app/services/tool_adapters.py" in commands[5].command
    assert "app/services/test_plan_execution_jobs.py" in commands[5].command
    assert "scripts/evaluate_test_plan.py" in commands[6].command
    assert commands[9].env["GENERATION_JOB_QUEUE_BACKEND"] == "in_memory"
    assert "scripts/check_generation_queue.py" in commands[9].command


def test_release_checks_can_skip_expensive_sections() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_type_check=False,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_queue_check=True,
            skip_diff_check=False,
        )
    )

    assert [command.name for command in commands] == [
        "type-check-test-agent",
        "git-diff-check",
    ]


def test_release_checks_can_skip_type_check() -> None:
    commands = build_default_commands(
        _args(
            skip_rag_eval=True,
            skip_pytest=True,
            skip_test_plan_eval=True,
            skip_type_check=True,
            skip_recovery_smoke=True,
            skip_readiness_check=True,
            skip_queue_check=True,
            skip_diff_check=False,
        )
    )

    assert [command.name for command in commands] == ["git-diff-check"]
