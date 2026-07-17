from pathlib import Path

from scripts.evaluate_test_execution import (
    DEFAULT_CASES_PATH,
    evaluate_cases,
    load_cases,
    main,
    summarize_results,
)


def test_evaluate_test_execution_fixture_passes() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases)
    summary = summarize_results(results)

    case_ids = {case["id"] for case in cases}
    assert "refund-flow-execution-001" in case_ids
    assert "http-header-blocked-execution-001" in case_ids

    assert summary["case_pass_rate"] == 1.0
    assert summary["report_status_rate"] == 1.0
    assert summary["summary_fact_quality_rate"] == 1.0
    assert summary["tool_status_rate"] == 1.0
    assert summary["coverage_match_rate"] == 1.0
    assert summary["defect_grounding_rate"] == 1.0
    assert summary["blocked_grounding_rate"] == 1.0
    assert summary["evidence_rate"] == 1.0


def test_evaluate_test_execution_main_outputs_json(capsys) -> None:
    assert (
        main(
            [
                "--json",
                "--fail-under-case-pass-rate",
                "1.0",
                "--fail-under-summary-fact-quality-rate",
                "1.0",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"case_pass_rate": 1.0' in output
    assert '"summary_fact_quality_rate": 1.0' in output
    assert '"tool_status_rate": 1.0' in output
    assert '"blocked_grounding_rate": 1.0' in output
    assert '"results"' in output


def test_load_execution_eval_cases_rejects_non_array_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    try:
        load_cases(path)
    except ValueError as exc:
        assert "must be a JSON array" in str(exc)
    else:
        raise AssertionError("expected ValueError")
