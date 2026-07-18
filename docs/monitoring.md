# 监控和告警

本文记录当前内部 metrics 接口和 Prometheus 告警规则模板。该能力面向受控内网或监控系统抓取，不建议公网直接暴露。

## Metrics 入口

运行指标接口受 `X-API-Key` 保护：

```http
GET /api/v1/operations/metrics
GET /api/v1/operations/metrics/prometheus
```

`/operations/metrics` 返回 JSON，适合排障和自定义脚本。`/operations/metrics/prometheus` 返回 Prometheus text exposition，适合 Prometheus scrape。

当前 Prometheus 指标包括：

- `ai_testcase_ready`
- `ai_testcase_readiness_check_status`
- `ai_testcase_llm_configured`
- `ai_testcase_llm_timeout_seconds`
- `ai_testcase_llm_max_retries`
- `ai_testcase_llm_call_total`
- `ai_testcase_llm_attempt_total`
- `ai_testcase_llm_retry_total`
- `ai_testcase_llm_call_duration_seconds`
- `ai_testcase_stage_total`
- `ai_testcase_stage_duration_seconds`
- `ai_testcase_job_count`
- `ai_testcase_job_active_count`
- `ai_testcase_generation_record_count`
- `ai_testcase_generation_gate_count`
- `ai_testcase_generation_usage_tokens`
- `ai_testcase_generation_estimated_cost`
- `ai_testcase_rq_registry_jobs`
- `ai_testcase_rq_worker_count`
- `ai_testcase_http_requests_total`
- `ai_testcase_http_request_duration_seconds`

## 抓取示例

直接调试时携带 `X-API-Key`：

```bash
curl -H 'X-API-Key: replace-with-service-api-key' \
  http://127.0.0.1:8000/api/v1/operations/metrics/prometheus
```

Prometheus 原生 scrape 配置通常不适合直接注入任意 `X-API-Key` 请求头。推荐在受控内网放一个轻量网关或 sidecar，由它向后端注入 `X-API-Key`，Prometheus 只抓取这个内部代理：

```yaml
scrape_configs:
  - job_name: ai-testcase-generator
    metrics_path: /metrics
    scheme: http
    static_configs:
      - targets:
          - ai-testcase-metrics-proxy:9100
```

不要为了方便抓取把 metrics 接口改成公网匿名访问。

建议的接入链路是：

- API 暴露 `/api/v1/operations/metrics` 和 `/api/v1/operations/metrics/prometheus`。
- 内部 metrics proxy 注入 `X-API-Key` 并转发到后端。
- Prometheus 通过 `docs/monitoring/prometheus-scrape-example.yml` 中的 scrape 片段抓取 proxy。
- Prometheus 通过 `rule_files` 加载 `docs/monitoring/prometheus-alert-rules.yml`。
- Alertmanager 通过 `docs/monitoring/alertmanager-route-example.yml` 接收并路由告警。

接入演练时先确认最小链路：

```bash
python scripts/check_monitoring_metrics.py --json
```

如果本地或 CI 环境已经安装 `promtool`，可以再做一次语法检查：

```bash
cd docs/monitoring
promtool check config prometheus-scrape-example.yml
promtool check rules prometheus-alert-rules.yml
```

`promtool` 不是本仓库依赖；没有安装时，至少保留上面的离线检查和模板审阅。

## 本地验证

上线或改动 metrics/告警模板前，可以先跑离线验证脚本：

```bash
python scripts/check_monitoring_metrics.py --json
```

该脚本不访问 Redis、数据库或 Prometheus；它会构造一份 synthetic metrics snapshot，调用当前 `format_prometheus_metrics()` 生成 Prometheus 文本，并检查关键 series 与 `docs/monitoring/prometheus-alert-rules.yml` 中的核心告警名/表达式是否仍然存在。`scripts/run_release_checks.py` 默认会执行该检查；需要临时跳过时使用 `--skip-monitoring-check`。

## 队列告警演练记录

Redis/RQ 或 MySQL 演练后，建议把队列告警快照保存为证据文件，便于复盘和阈值校准：

```bash
python scripts/check_queue_alerts.py --json \
  --output-json data/ops-drills/queue-alerts-$(date +%Y%m%d-%H%M%S).json
```

生产或预发环境建议显式带上阈值，避免只保存默认配置：

```bash
python scripts/check_queue_alerts.py --json \
  --require-worker \
  --max-active-jobs 20 \
  --max-rq-queued 50 \
  --max-rq-started 20 \
  --max-rq-failed 0 \
  --fail-on-warning \
  --output-json data/ops-drills/queue-alerts-$(date +%Y%m%d-%H%M%S).json
```

输出文件包含 `generated_at`、阈值、三个队列的 metrics、alerts 和原始 snapshot。文件可作为 Redis/MySQL outage、RQ worker stability 和 workflow RQ/MySQL smoke 的演练附件；真实环境的历史记录应保存在团队运维仓库或受控对象存储，不建议提交到本代码仓库。

## 阈值校准

正式接入后，先观察一个完整业务周期，再调整告警阈值。建议按下面顺序校准：

- 先看 `AITestcaseServiceNotReady` 和 `AITestcaseReadinessCheckError`，确认是否存在启动抖动或配置缺失噪声。
- 再看 `AITestcaseQueuedJobsBacklog`、`AITestcaseActiveJobsStuck`、`AITestcaseRQFailedRegistryNotEmpty` 和 `AITestcaseRQNoWorkerForActiveJobs`，把队列积压和 worker 缺失的门槛调到真实容量附近。
- 再看 `AITestcaseLLMCallFailuresObserved`、`AITestcaseLLMRetriesObserved`、`AITestcaseStageFailuresObserved` 和 `AITestcaseStageP95LatencyHigh`，按环境和业务阶段分别校准。
- 再看 `AITestcaseGenerationFailuresObserved`、`AITestcaseGenerationGatePending`、`AITestcaseGenerationUsageTokensHigh` 和 `AITestcaseGenerationEstimatedCostHigh`，避免把开发环境和生产环境混用。
- 最后再看 `AITestcaseHTTP5xxRateHigh`，确认接口层 5xx 不是由短时维护或健康检查引起。

校准时需要保留的记录：

- 采样窗口和观察日期。
- 每个告警当前阈值、建议阈值和调整原因。
- 触发样本数、误报样本数和是否需要按环境拆分。
- 是否需要在 Alertmanager 侧做静默、聚合或抑制。

## 告警规则模板

规则模板位于 [monitoring/prometheus-alert-rules.yml](monitoring/prometheus-alert-rules.yml)。

当前模板覆盖：

- readiness 整体失败。
- 单个 readiness check 失败或持续 warning。
- LLM key 未配置。
- LLM 调用失败增长。
- LLM retry 增长。
- 业务阶段失败增长。
- 业务阶段 P95 耗时持续偏高。
- job queued backlog。
- active jobs 长时间未清空。
- 生成失败记录增长。
- 待处理 generation gate 积压。
- 生成 token usage 或 estimated cost 超过阈值。
- Redis/RQ failed registry 非空。
- RQ 有活跃任务但没有 worker。
- HTTP 5xx 错误率持续升高。

模板阈值是受控环境的起点，不是生产容量结论。正式接入前应按业务规模调整：

- `AITestcaseQueuedJobsBacklog` 的 queued job 阈值。
- `AITestcaseActiveJobsStuck` 的持续时间。
- `AITestcaseGenerationFailuresObserved` 是否按环境区分 warning/critical。
- `AITestcaseGenerationGatePending` 的 pending gate 容忍时间。
- `AITestcaseGenerationUsageTokensHigh` 和 `AITestcaseGenerationEstimatedCostHigh` 的窗口与预算阈值。
- `AITestcaseLLMCallFailuresObserved` 和 `AITestcaseLLMRetriesObserved` 的错误码、模型和时间窗口。
- `AITestcaseStageFailuresObserved` 和 `AITestcaseStageP95LatencyHigh` 的 workflow/stage 范围、时间窗口和耗时阈值。
- RQ worker 是否在所有环境都必须存在。
- LLM 未配置在开发环境是否只作为 warning。

## 当前限制

当前 metrics 主要覆盖配置状态、job 状态计数、生成历史成功/失败、generation gate 状态计数、历史 token/cost 聚合、readiness、RQ registry/worker、HTTP 请求量、状态码和耗时桶、LLM call/attempt/retry/错误码/耗时桶，以及生成、测试计划执行、测试 Agent workflow 的业务阶段计数和耗时桶。阶段指标是进程内聚合，服务重启后会清零；多副本部署时需要由 Prometheus 按实例标签汇总。
