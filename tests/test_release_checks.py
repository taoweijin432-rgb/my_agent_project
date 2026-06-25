from argparse import Namespace

from scripts.run_release_checks import build_default_commands


def _args(**overrides):
    values = {
        "python": "python",
        "skip_rag_eval": False,
        "skip_pytest": False,
        "skip_diff_check": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_release_checks_include_rag_pytest_and_diff_by_default() -> None:
    commands = build_default_commands(_args())

    names = [command.name for command in commands]

    assert names == [
        "login-rag-ingest",
        "login-rag-eval",
        "pytest-core",
        "git-diff-check",
    ]
    assert commands[0].env["CHROMA_COLLECTION"] == "login_rag_eval_hash"
    assert "tests/fixtures/login_rag_eval_cases.json" in commands[1].command
    assert "tests/test_generator.py" in commands[2].command


def test_release_checks_can_skip_expensive_sections() -> None:
    commands = build_default_commands(
        _args(skip_rag_eval=True, skip_pytest=True, skip_diff_check=False)
    )

    assert [command.name for command in commands] == ["git-diff-check"]
