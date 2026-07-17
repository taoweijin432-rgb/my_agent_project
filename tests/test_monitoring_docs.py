from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_prometheus_alert_rules_template_mentions_core_alerts() -> None:
    rules_path = PROJECT_ROOT / "docs" / "monitoring" / "prometheus-alert-rules.yml"

    content = rules_path.read_text(encoding="utf-8")

    assert "groups:" in content
    assert "AITestcaseServiceNotReady" in content
    assert "AITestcaseLLMNotConfigured" in content
    assert "AITestcaseLLMCallFailuresObserved" in content
    assert "AITestcaseLLMRetriesObserved" in content
    assert "AITestcaseStageFailuresObserved" in content
    assert "AITestcaseStageP95LatencyHigh" in content
    assert "AITestcaseQueuedJobsBacklog" in content
    assert "AITestcaseGenerationFailuresObserved" in content
    assert "AITestcaseGenerationGatePending" in content
    assert "AITestcaseGenerationUsageTokensHigh" in content
    assert "AITestcaseGenerationEstimatedCostHigh" in content
    assert "AITestcaseRQFailedRegistryNotEmpty" in content
    assert "AITestcaseRQNoWorkerForActiveJobs" in content
    assert "AITestcaseHTTP5xxRateHigh" in content
    assert "ai_testcase_ready == 0" in content
    assert 'ai_testcase_llm_call_total{status="failed"}' in content
    assert "ai_testcase_llm_retry_total" in content
    assert 'ai_testcase_stage_total{status=~"failed|blocked"}' in content
    assert "histogram_quantile(0.95" in content
    assert "ai_testcase_stage_duration_seconds_bucket" in content
    assert 'ai_testcase_job_count{status="queued"} > 20' in content
    assert 'ai_testcase_generation_record_count{status="failed"}' in content
    assert 'ai_testcase_generation_gate_count{status="pending"} > 0' in content
    assert 'ai_testcase_generation_usage_tokens{token_type="total_tokens_estimate"}' in content
    assert "ai_testcase_generation_estimated_cost > 100" in content
    assert 'ai_testcase_http_requests_total{status_class="5xx"}' in content


def test_prometheus_scrape_example_mentions_proxy_and_alerting() -> None:
    config_path = PROJECT_ROOT / "docs" / "monitoring" / "prometheus-scrape-example.yml"

    content = config_path.read_text(encoding="utf-8")

    assert "ai-testcase-generator" in content
    assert "ai-testcase-metrics-proxy:9100" in content
    assert "rule_files:" in content
    assert "alerting:" in content
    assert "alertmanager:9093" in content
    assert "prometheus-alert-rules.yml" in content


def test_alertmanager_route_example_mentions_service_receivers() -> None:
    config_path = (
        PROJECT_ROOT / "docs" / "monitoring" / "alertmanager-route-example.yml"
    )

    content = config_path.read_text(encoding="utf-8")

    assert "ai-testcase-generator-default" in content
    assert "ai-testcase-generator-critical" in content
    assert "ai-testcase-generator-warning" in content
    assert 'severity="critical"' in content
    assert 'severity="warning"' in content
    assert 'alertname="AITestcaseServiceNotReady"' in content
    assert "webhook_configs:" in content
    assert "group_by:" in content
    assert "inhibit_rules:" in content


def test_monitoring_guide_links_alert_rules_template() -> None:
    guide_path = PROJECT_ROOT / "docs" / "monitoring.md"

    content = guide_path.read_text(encoding="utf-8")

    assert "GET /api/v1/operations/metrics/prometheus" in content
    assert "monitoring/prometheus-alert-rules.yml" in content
    assert "monitoring/prometheus-scrape-example.yml" in content
    assert "monitoring/alertmanager-route-example.yml" in content
    assert "X-API-Key" in content
    assert "ai_testcase_llm_call_total" in content
    assert "ai_testcase_llm_attempt_total" in content
    assert "ai_testcase_llm_retry_total" in content
    assert "ai_testcase_stage_total" in content
    assert "ai_testcase_stage_duration_seconds" in content
    assert "ai_testcase_generation_record_count" in content
    assert "ai_testcase_generation_gate_count" in content
    assert "ai_testcase_generation_usage_tokens" in content
    assert "ai_testcase_generation_estimated_cost" in content
    assert "ai_testcase_http_requests_total" in content
    assert "promtool check config" in content
    assert "promtool check rules" in content
