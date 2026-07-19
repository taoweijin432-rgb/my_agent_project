import json

from scripts.check_secrets import build_summary, main, scan_paths


def test_secret_scan_detects_high_confidence_values(tmp_path) -> None:
    token = "sk-" + ("a" * 32)
    app_key = "prod-" + ("b" * 24)
    source = tmp_path / "app.py"
    openai_key_name = "OPENAI_API" + "_KEY"
    app_key_name = "APP_API" + "_KEY"
    source.write_text(
        f"{openai_key_name}={token}\n{app_key_name}={app_key}\n",
        encoding="utf-8",
    )

    findings = scan_paths([source], root=tmp_path)

    assert [finding.rule for finding in findings] == [
        "openai_api_key",
        "secret_assignment",
        "secret_assignment",
    ]
    assert findings[0].path == "app.py"
    assert token not in findings[0].preview
    assert app_key not in findings[-1].preview


def test_secret_scan_allows_placeholders_and_test_fake_values(tmp_path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "APP_API_KEY=replace-with-strong-service-api-key\n"
        "ZHIPU_API_KEY=${{ secrets.ZHIPU_API_KEY }}\n"
        "MYSQL_PASSWORD=your_agent_password\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_fake.py"
    test_file.parent.mkdir()
    test_file.write_text(
        "ZHIPU_API_KEY=secret-zhipu-key\n"
        "Authorization: Bearer secret-token\n",
        encoding="utf-8",
    )

    assert scan_paths([env_example, test_file], root=tmp_path) == []


def test_secret_scan_main_returns_nonzero_for_findings(
    tmp_path,
    capsys,
) -> None:
    token = "ghp_" + ("A" * 32)
    token_name = "GITHUB" + "_TOKEN"
    source = tmp_path / "settings.env"
    source.write_text(f"{token_name}={token}\n", encoding="utf-8")

    exit_code = main(["--root", str(tmp_path), "--path", str(source), "--json"])

    assert exit_code == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is False
    assert summary["finding_count"] == 2
    assert summary["findings"][0]["rule"] == "github_token"
    assert token not in json.dumps(summary)


def test_secret_scan_summary_reports_ok() -> None:
    summary = build_summary([], scanned_files=2)

    assert summary == {
        "ok": True,
        "scanned_files": 2,
        "finding_count": 0,
        "findings": [],
    }
