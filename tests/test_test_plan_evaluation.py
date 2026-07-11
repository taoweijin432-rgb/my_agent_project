from pathlib import Path

from scripts.evaluate_test_plan import (
    DEFAULT_CASES_PATH,
    evaluate_cases,
    load_cases,
    main,
    summarize_results,
)
from app.services.test_plan_generator import TestPlanGenerator


def test_evaluate_test_plan_fixture_passes_with_rule_based_generator() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases, generator=TestPlanGenerator())
    summary = summarize_results(results)

    assert summary["case_pass_rate"] == 1.0
    assert summary["tool_hit_rate"] == 1.0
    assert summary["test_type_hit_rate"] == 1.0
    assert summary["risk_keyword_hit_rate"] == 1.0


def test_evaluate_test_plan_main_outputs_json(capsys) -> None:
    assert main(["--json", "--fail-under-case-pass-rate", "1.0"]) == 0

    output = capsys.readouterr().out
    assert '"case_pass_rate": 1.0' in output
    assert '"results"' in output


def test_load_cases_rejects_non_array_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    try:
        load_cases(path)
    except ValueError as exc:
        assert "must be a JSON array" in str(exc)
    else:
        raise AssertionError("expected ValueError")
