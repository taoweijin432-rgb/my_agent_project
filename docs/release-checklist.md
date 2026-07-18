# 发布检查清单

建议发布标签：`v0.2-async-hitl-baseline`

发布目标：形成一个可运行、可集成、可发布的 RAG Agent 后端基线版本，并提供轻量前端工作台用于本地操作和演示。该版本不是公网多租户生产最终态，后续升级重点是生产数据库、队列治理、Agent 框架、前端后台和可观测性。

## 1. 发布范围

本次发布包含：

- FastAPI REST API。
- 智谱 LLM JSON Mode 调用封装。
- Chroma RAG 知识库导入、查询、文档 upsert/delete。
- 轻量 Agent workflow：需求分析、知识检索、召回不足 query rewrite、测试策略规划、Prompt 构造、LLM 生成、Schema 校验、后处理、Reviewer、门控、usage 估算。
- `GenerationWorkflowState` 短期记忆和 `workflow_steps` 节点轨迹。
- Reviewer Agent 本地质量审查和可选重试。
- 预算门控、质量门控和结构化 human-in-the-loop 响应。
- 门控事件持久化、待处理查询和人工审批/驳回闭环。
- 生成历史数据库持久化、详情回放和质量报告。
- 需求覆盖率评估接口、缺口报告和人工确认后知识库沉淀接口。
- Excel 导出和 pytest 自动化模板导出。
- 登录场景效率对比脚本和报告。
- 异步生成任务队列、Redis/RQ 外部队列、worker 进程和队列满 429 背压。
- 测试 Agent workflow job：从需求生成测试计划、执行工具、汇总报告，并把真实 LLM 计划生成放入后台任务。
- 默认 LangGraph workflow backend，`local` backend 保留为 fallback 和行为对照。
- API key、CORS、应用内限流、请求 ID、耗时响应头、生产启动配置校验。
- 内部运行指标接口，提供 JSON 和 Prometheus 文本输出，覆盖 readiness、job 状态计数、队列 registry/worker 和 LLM 配置指标，并提供 Prometheus 告警规则模板。
- Dockerfile、Docker Compose 模板、运行配置示例和部署说明。
- React + Vite 前端工作台，覆盖生成、异步任务、测试计划生成/执行/报告导出、知识库、历史、门控和覆盖率评估的操作入口。
- 项目说明、Agent 架构说明、RAG 评估说明和部署文档。

## 2. 发布前必须验证

代码验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

推荐使用统一发布检查入口：

```bash
./.venv/bin/python scripts/run_release_checks.py
```

该入口默认执行：

- 隔离登录知识库导入。
- 隔离订单退款知识库导入。
- 登录和订单退款 RAG 固定评估，要求 source hit 和 keyword hit 均为 100%。
- 核心 pytest 回归，包括 API 路由、导出、知识库和中间件测试；这些测试不依赖 FastAPI `TestClient`，适合沙箱环境运行。
- 测试 Agent 契约模块 mypy 类型检查，覆盖测试计划模型、工具 adapter、artifact store、执行编排、workflow job、执行 job、store、报告和 RQ worker。
- 测试计划生成固定评估，验证工具选择、测试类型和风险关键词命中率。
- 测试执行报告固定评估，验证报告 status、摘要事实一致性、需求覆盖、缺陷归因、原因分类、原因感知建议、建议步骤 grounding、next-action 动词质量、证据 artifact/output 可追溯性和 Markdown/JSON 导出事实一致性。
- 测试执行端到端固定评估，验证 HTTP/pytest adapter、执行编排、报告构建、缺陷归因、阻塞归因、执行证据片段、退款多步骤业务流和 HTTP header 权限阻塞场景。
- 测试 Agent workflow 固定评估，验证需求读取、规则 planner、工具执行、报告构建、风险关键词、报告状态、摘要事实一致性、覆盖率、缺陷归因、原因分类、原因感知建议、建议步骤 grounding、next-action 动词质量和证据 artifact/output 可追溯性的整链路，当前覆盖退款失败审计、权限/鉴权失败、异步队列状态超时、支付对账幂等冲突、库存预占锁定异常、通知重试失败、文件导出越权下载、用户资料参数校验失败、退款金额不一致、异步终态不一致、结账前置失败、支付回调幂等冲突、pytest 断言失败、SQL adapter 缺失和人工确认未执行 15 条链路。
- 测试 Agent workflow job 单测，验证 in-memory/RQ 队列、SQLite 持久化、stale running 恢复、RQ worker、MySQL schema 基线、耗时观测契约和阶段失败码。
- 内部 metrics 单测，验证 JSON snapshot、Prometheus 文本输出、job 状态计数、readiness 和 LLM 配置指标。
- 异步任务 stale 恢复 smoke，验证过期 `running` 任务会失败且 fresh 任务不被误杀。
- 测试计划执行 worker smoke，验证多 job 连续执行和 stale 恢复不误杀 fresh job。
- 测试计划执行 runtime smoke，验证 SQLite job 保留期清理、队列满背压和 worker 多任务稳定性。
- 内部 readiness 检查，验证运行目录、数据库任务状态库和队列依赖。
- 生成队列观测检查，输出数据库任务状态统计、队列快照和健康判断，默认使用临时 SQLite/in-memory 配置避免污染本地数据。
- 测试计划执行队列观测检查，按 job function 过滤共享 RQ 队列中的执行任务，避免把生成任务混进统计。
- 测试 Agent workflow 队列观测检查，按 job function 过滤共享 RQ 队列中的 workflow 任务，避免把用例生成任务和测试计划执行任务混进统计。
- `git diff --check`。

可选真实模型验证：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-test-plan-eval
```

该检查会运行 `scripts/evaluate_test_plan.py --use-llm`，不启用 deterministic fallback；因此需要配置真实 `ZHIPU_API_KEY`，失败会暴露模型输出、Prompt 或上游模型配置问题。默认发布检查不启用该项，只保证无密钥环境可跑；重要发布或模型切换后应手动启用真实 LLM 门禁。

可选真实模型 workflow 验证：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-workflow-eval
```

该检查会运行 `scripts/evaluate_test_agent_workflow.py --use-llm --concurrency 1 --case-delay-seconds 2 --strict-plan-tools --strict-plan-test-types --strict-http-headers`，从需求样本开始验证真实模型生成的计划是否能通过工具执行、报告状态、摘要事实一致性、覆盖率、风险关键词、缺陷归因、原因分类、原因感知建议、建议步骤 grounding、next-action 质量、HTTP header 值质量和证据 artifact/output 可追溯性门禁。失败时输出 `failure_codes` 和 `failure_reasons`，用于定位是计划工具、测试类型、风险关键词、执行状态、报告摘要、覆盖率、缺陷归因、原因分类、原因感知建议、建议 grounding、next-action 质量、证据 artifact 还是证据片段问题。该项同样需要真实 `ZHIPU_API_KEY`，不启用 deterministic fallback，不放入默认 CI；它是模型约束效果的主验证入口。

workflow eval 校验对象是实际 generator 输出的 `TestPlan`：默认路径校验规则 planner 的真实输出，`--use-llm` 路径校验真实 LLM 输出；不要用 fake generator 或手工构造的模拟计划替代该门禁结论。LLM planner 会对真实模型返回的 HTTP tool args 做契约归一化：只保留真实 adapter 可执行字段，映射常见别名，从需求原文补齐明确的 method/path/status，并过滤不在安全白名单内的 header；当存在结构化需求时，`test_types` 以需求文本推断结果为准，避免模型额外枚举测试类型导致 strict 门禁漂移。

如果要检查模型是否“刚好够用”之外的输出质量，应显式启用 strict 模式。strict 模式会把工具集合和测试类型集合改为精确匹配，并校验 HTTP `Accept`/`Content-Type` 这类 header 值是否是完整 media type：

```bash
./.venv/bin/python scripts/evaluate_test_agent_workflow.py --json --use-llm \
  --concurrency 1 \
  --case-delay-seconds 2 \
  --case-slice 0:3 \
  --strict-plan-tools \
  --strict-plan-test-types \
  --strict-http-headers \
  --fail-under-case-pass-rate 1.0 \
  --fail-under-http-header-value-rate 1.0 \
  --fail-under-summary-fact-quality-rate 1.0 \
  --fail-under-reason-classification-rate 1.0 \
  --fail-under-reason-aware-recommendation-rate 1.0 \
  --fail-under-recommendation-grounding-rate 1.0 \
  --fail-under-next-action-quality-rate 1.0 \
  --fail-under-evidence-artifact-quality-rate 1.0
```

默认 workflow eval 允许模型生成额外测试类型，适合判断核心链路是否可跑通；strict 模式适合判断模型输出是否足够收敛，二者不要混为同一个质量结论。deterministic/offline eval 只作为快速回归保护，不推荐用于评估真实模型约束效果。

2026-07-15 使用当前默认模型 `glm-4-flash` 完成当前 15 个需求到报告样本的真实 LLM strict 覆盖：原 11 个样本全量 strict eval 与新增 4 个真实业务样本在 `json_assertions` 新契约下分批 strict eval 均通过，`case_pass_rate=1.0`，`tool_args_schema_rate=1.0`，`plan_tool_hit_rate=1.0`，`plan_test_type_hit_rate=1.0`，`report_status_rate=1.0`，`reason_classification_rate=1.0`，`reason_aware_recommendation_rate=1.0`，`evidence_rate=1.0`，无 `failure_code_counts`，无 fallback、无 retry、无 timeout/429。新增 4 个样本耗时为 `plan_generation.avg=29567.073ms`，`plan_generation.max=35863.873ms`。当前默认规则 workflow eval 已扩展到 15 个样本，并覆盖 422 参数校验失败、金额不一致、异步终态不一致、前置失败和回调幂等冲突；其中金额不一致和异步终态不一致已使用 HTTP `json_assertions` 校验响应 body 字段。模型质量结论以真实 LLM strict workflow eval 为准，deterministic eval 只作为快速回归保护。当前模型下长耗时问题没有复现，之前慢调用应按模型或上游状态差异处理；后续每次模型切换都要重新跑真实 strict eval，并把 `timeout_count`、`retry_count_total`、429 计数和耗时写入 benchmark history。

workflow job 的 `result.timing.stages[].details` 已支持非敏感 LLM 调用观测。真实 LLM 计划生成阶段会记录 `used_llm`、`used_fallback` 和 `llm` metrics，包括模型名、base URL、timeout/retry 配置、attempt/retry 次数、总耗时、每次 attempt 耗时和错误类别；不记录 API key、prompt messages、业务输入或模型原始响应。

workflow eval 的 JSON summary 已汇总同一套 LLM observability：`llm_observability.observed_cases`、`attempt_count_total`、`retry_count_total`、`timeout_count`、`error_code_counts`、`cache_status_counts` 和 LLM duration 统计。前端 workflow job 详情页也会在真实 LLM job 中展示 LLM 尝试次数、重试次数、总耗时、缓存状态、最后状态和是否使用 fallback。

LLM retry 策略已区分错误类型：`timeout`、`rate_limited`、`http_5xx`、网络类 `http_error`、`invalid_json` 和 `malformed_response` 会在 `LLM_MAX_RETRIES` 预算内重试；除 429 之外的 `http_4xx` 这类鉴权、配额或请求配置问题不会重试。`LLM_RETRY_BACKOFF_SECONDS` 控制指数 backoff 基数，默认 `0` 保持本地/CI 快速，真实 smoke 可设置为 `0.5` 或 `1.0` 降低上游抖动时的立即重打。

可选真实模型 workflow 延迟 benchmark：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-workflow-benchmark
```

该检查会运行 `scripts/evaluate_test_agent_workflow.py --use-llm --concurrency 1 --case-delay-seconds 2`，不启用 deterministic fallback，也不启用缓存；它重点输出 `timing_ms`，并用宽松阈值约束 `total.max <= 240000ms`、`plan_generation.max <= 180000ms`。结果会追加写入 `data/llm-workflow-benchmark-history.jsonl`，记录模型、base URL、并发、分批参数、通过率、失败码和耗时汇总，不记录 API key、prompt messages 或模型原始响应。该项用于对比真实模型慢调用和模型切换影响，不替代上面的质量强门禁。

小型 LLM workflow dry-run 模板：

```bash
export ZHIPU_API_KEY='真实 key'
export LLM_TIMEOUT_SECONDS=120
export LLM_MAX_RETRIES=1
export LLM_RETRY_BACKOFF_SECONDS=0.5
./.venv/bin/python scripts/evaluate_test_agent_workflow.py --json --use-llm \
  --concurrency 1 \
  --case-slice 0:2 \
  --case-delay-seconds 2 \
  --fail-over-total-ms 240000 \
  --fail-over-plan-generation-ms 180000 \
  --benchmark-history-jsonl data/llm-workflow-benchmark-history.jsonl \
  --fail-under-case-pass-rate 1.0 \
  --fail-under-tool-args-schema-rate 1.0 \
  --fail-under-plan-tool-hit-rate 1.0 \
  --fail-under-plan-test-type-hit-rate 1.0 \
  --fail-under-plan-step-count-rate 1.0 \
  --fail-under-risk-keyword-hit-rate 1.0 \
  --fail-under-report-status-rate 1.0 \
  --fail-under-summary-fact-quality-rate 1.0 \
  --fail-under-tool-status-rate 1.0 \
  --fail-under-coverage-match-rate 1.0 \
  --fail-under-defect-grounding-rate 1.0 \
  --fail-under-reason-classification-rate 1.0 \
  --fail-under-reason-aware-recommendation-rate 1.0 \
  --fail-under-recommendation-grounding-rate 1.0 \
  --fail-under-next-action-quality-rate 1.0 \
  --fail-under-evidence-artifact-quality-rate 1.0 \
  --fail-under-evidence-rate 1.0
```

开发调试时可以复用真实 LLM 历史输出，减少重复等待和 token 消耗：

```bash
./.venv/bin/python scripts/evaluate_test_agent_workflow.py --json --use-llm \
  --concurrency 2 \
  --use-cache
```

缓存目录默认为 `data/llm-eval-cache/`，已被 `.gitignore` 忽略。缓存 key 包含模型、base URL、prompt 模板版本和完整 messages hash，不包含 API key。发布前如需强制重新请求真实模型并覆盖缓存，使用 `--refresh-cache`。

失败诊断解读：

| failure code | 优先排查方向 |
| --- | --- |
| `tool_args_schema_mismatch` | 模型生成的工具参数经归一化后仍不符合 adapter schema，例如 HTTP 缺少可解析的 `path` 或状态码非法；优先修 Prompt 和 LLM planner 的契约归一化。 |
| `plan_tool_mismatch` | Prompt 或模型输出没有选择期望工具，例如应为 `http` 却生成了 `manual`。 |
| `plan_test_type_mismatch` | Prompt 或模型输出漏掉 `permission`、`security`、`exception` 等测试类型。 |
| `plan_step_count_mismatch` | 模型合并、漏生成或额外生成步骤，先检查需求拆分和 `max_steps`。 |
| `risk_keyword_mismatch` | 风险识别不足，通常需要补 Prompt 中的风险归纳规则或 few-shot。 |
| `report_status_mismatch` | 执行结果汇总不符合预期，先看 tool run 状态，再看报告汇总逻辑。 |
| `summary_fact_quality_mismatch` | 报告摘要缺少或写错 status、执行数、覆盖率或 passed/failed/blocked/skipped 计数，优先检查 `TestExecutionReport.summary` 构造。 |
| `tool_status_mismatch` | 工具参数不可执行、mock 响应未命中、header 被 adapter 安全 allowlist 拦截，或模型生成的 method/path/status 不符合 fixture。 |
| `coverage_mismatch` | step 与 requirement 绑定错误，或报告覆盖率计算暴露计划结构问题。 |
| `defect_grounding_mismatch` | 失败步骤没有进入缺陷归因，或缺陷归因到了错误 step。 |
| `reason_classification_mismatch` | 报告结构化原因分类与测评集期望不一致，优先检查 `reason_classifications`、tool output summary 和分类规则；当前覆盖 `timeout`、`permission_denied`、`permission_not_enforced`、`conflict`、`upstream_unavailable`、`auth_failure`、`validation_error`、`response_assertion_mismatch`、`adapter_missing`、`assertion_mismatch`、`manual_confirmation_required` 等类型。 |
| `reason_aware_recommendation_mismatch` | 报告建议没有根据原因分类给出匹配动作，例如 timeout 需提到超时/重试，conflict 需提到幂等/冲突，permission 类需提到权限或身份。 |
| `recommendation_grounding_mismatch` | 报告建议没有绑定 failed、blocked 或 skipped 的具体 step，或建议引用了不可行动的 step。 |
| `next_action_quality_mismatch` | 报告建议虽然引用了 step，但没有包含期望动作关键词；按状态检查 failed 的复查/检查/定位/修复、blocked 的处理/配置/恢复、skipped 的确认/补充。 |
| `evidence_artifact_quality_mismatch` | 报告 Markdown 中缺少 failed、blocked 或 skipped step 的 artifact 路径；无 artifact 时至少要包含该 step 的 output summary。 |
| `evidence_mismatch` | 报告或 tool output 缺少期望证据片段，优先检查 artifact/output summary。 |

可选 Docker 运行依赖故障演练：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-runtime-outage-smoke
```

该检查会调用 `scripts/smoke_runtime_dependency_outage.py`，短暂停止 Redis/MySQL，验证 `scripts/check_generation_queue.py` 能报告明确故障，然后恢复服务并重新通过检查。它会改变本机 Docker 服务状态，只适合人工演练或受控环境，不放入默认 CI。

可选 Redis/RQ + MySQL worker 稳定性演练：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-rq-mysql-worker-stability-smoke
```

该检查会调用 `scripts/smoke_rq_mysql_worker_stability.py`，启动临时 worker 容器，提交多条测试计划执行 job，校验 passed/failed 报告混合结果和执行 artifact，然后删除临时 worker。它依赖 Docker、Redis、MySQL profile 和当前镜像，只适合人工演练或受控环境，不放入默认 CI。`DATABASE_BACKEND=mysql` 时，该检查会验证 `test_plan_execution_jobs` 的 MySQL 持久化路径。

更长时长演练可以直接运行脚本并提高轮次、每轮 job 数和 worker 数：

```bash
./.venv/bin/python scripts/smoke_rq_mysql_worker_stability.py --json --rounds 5 --jobs-per-round 6 --failure-count 2 --worker-count 2
```

长时演练通过条件：总 job 数符合预期，每轮都产生 passed/failed 混合报告，每个 job 至少有一个 artifact，且每轮后的测试计划执行队列 alert 通过，无 active job、无 RQ failed registry、无 MySQL/RQ 状态不一致。

可选测试 Agent workflow Docker/RQ + MySQL 实机演练：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-test-agent-workflow-rq-mysql-smoke
```

该检查会调用 `scripts/smoke_test_agent_workflow_rq_mysql.py`，在 MySQL profile 环境中启动临时 RQ worker，从 `TestAgentWorkflowRequest` 提交后台 workflow job，验证真实 API、Redis、MySQL、RQ worker、HTTP adapter、artifact 产出、`TestExecutionReport`、耗时汇总、吞吐汇总和 workflow 队列 alert。它依赖 Docker、Redis、MySQL profile 和当前镜像，只适合人工演练或受控环境，不放入默认 CI。`DATABASE_BACKEND=mysql` 时，该检查会验证 workflow job 状态写入 MySQL 持久化路径。

常驻服务模式验证使用 Compose override 同时对齐 API 和 worker：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d --build mysql redis api worker
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql exec api \
  python scripts/check_readiness.py --json
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql exec api \
  python scripts/check_queue_alerts.py --json --require-worker --max-rq-failed 0
```

该路径验证常驻 API 和 worker 使用同一个 MySQL/RQ 配置，而不是只依赖 smoke 脚本启动的临时 worker。

常驻服务模式负载验证可以继续提交多轮 deterministic workflow job，并在每轮后检查队列告警：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql exec api \
  python scripts/smoke_service_mode_workflow_load.py \
    --rounds 3 \
    --jobs-per-round 4 \
    --require-worker \
    --max-rq-failed 0 \
    --fail-over-max-queue-wait-ms 60000 \
    --fail-over-max-job-total-ms 120000 \
    --fail-under-throughput-jobs-per-second 0.01 \
    --json
```

该脚本通过运行中的 HTTP API 提交 job，再由常驻 worker 消费；适合验证服务模式吞吐、排队耗时、MySQL 写回和队列告警闭环。

更长时长或并行 worker 演练可以直接运行脚本并提高轮次、每轮 job 数和 worker 数：

```bash
./.venv/bin/python scripts/smoke_test_agent_workflow_rq_mysql.py --json \
  --rounds 2 \
  --jobs-per-round 2 \
  --worker-count 2 \
  --fail-over-max-queue-wait-ms 60000 \
  --fail-under-throughput-jobs-per-second 0.001
```

workflow 实机演练通过条件：所有 workflow job 进入 `succeeded`，报告为 `passed`，每个 job 至少有一个执行 artifact，需求覆盖计数符合预期，输出 `timing_summary_ms` 和 `throughput`，且每轮后的 workflow 队列 alert 通过，无 active job、无 RQ failed registry、无 MySQL/RQ 状态不一致。吞吐门禁可用 `--fail-over-max-queue-wait-ms` 和 `--fail-under-throughput-jobs-per-second` 显式约束。

可选队列 metrics/alert 阈值检查：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-queue-alert-check
```

该检查会调用 `scripts/check_queue_alerts.py`，聚合生成队列和测试计划执行队列的 `metrics` 与 `alerts`。默认把 RQ failed registry 超过 0 视为 error，并检查 worker heartbeat；生产环境可直接运行脚本并显式配置 `--require-worker`、`--max-active-jobs`、`--max-rq-queued`、`--max-rq-started` 和 `--fail-on-warning`。

容量观察或阈值校准时，使用采样脚本保存多次快照和汇总：

```bash
./.venv/bin/python scripts/collect_queue_alert_samples.py \
  --samples 60 \
  --interval-seconds 60 \
  --require-worker \
  --max-rq-failed 0 \
  --fail-on-warning \
  --output-jsonl data/ops-drills/queue-alert-samples-$(date +%Y%m%d-%H%M%S).jsonl \
  --output-summary-json data/ops-drills/queue-alert-summary-$(date +%Y%m%d-%H%M%S).json \
  --json
```

该脚本复用 `check_queue_alerts.py` 的队列快照和阈值逻辑，每行写入一次完整 report，最终 summary 输出 observed maxima、alert counts 和带 headroom 的候选阈值。候选阈值只作为观察窗口参考，不能替代完整业务周期和压测结论。

默认发布检查还会执行本地监控 metrics/alert 模板验证：

```bash
./.venv/bin/python scripts/check_monitoring_metrics.py --json
```

该检查使用 synthetic snapshot 生成 Prometheus 文本，验证关键 series、`docs/monitoring/prometheus-alert-rules.yml` 中的核心告警表达式、`docs/monitoring/prometheus-scrape-example.yml` 和 `docs/monitoring/alertmanager-route-example.yml` 的关键接入片段仍然匹配；不连接 Redis、数据库或真实 Prometheus。

接入真实监控系统前，建议先把 `docs/monitoring/prometheus-scrape-example.yml` 和 `docs/monitoring/alertmanager-route-example.yml` 复制到目标环境的监控仓库或配置管理系统，再按环境名、接收人和 webhook 地址做替换。

前端验证：

```bash
cd frontend
npm test
npm run build
```

如需执行真实 LLM 强门控 smoke，显式增加：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-smoke
```

该模式会启动本地 FastAPI 服务并调用真实模型，验证不达标请求返回 `quality_gate_failed` 409、达标请求返回 200。它会消耗模型额度，不建议放入默认 CI。

CI 验证：

- `.github/workflows/ci.yml` 会在 push 和 pull request 时运行 `scripts/run_release_checks.py`。
- `.github/workflows/ci.yml` 的 `frontend-build` job 会运行 `npm test` 和 `npm run build`。
- 真实 LLM smoke 保留为 `workflow_dispatch` 手动触发，需勾选 `run_llm_smoke` 并配置 GitHub Secret：`ZHIPU_API_KEY`。
- 不把真实 API key 写入 workflow 文件、README 或示例配置。

敏感信息扫描：

- 扫描真实服务 key、模型 key、云厂商 key 和 `.env/config.py` 泄漏。
- 扫描范围覆盖 `.github`、示例环境文件、`app/`、`docs/`、`scripts/`、`tests/`、`README.md`、Docker 文件和依赖文件。
- 不在文档中固化具体 key pattern，避免发布文档本身被扫描命令误报。
- 检查测试执行 artifact、`ToolRun.output_summary`、报告 evidence、Markdown/JSON 导出、历史记录和异常日志，不应出现 token、cookie、password、api key 或业务敏感响应片段。
- 使用包含假 token、假 cookie、假 password、假 API key 的 fixture 验证脱敏链路；测试断言应检查原始敏感值不存在，而不是只检查 `[redacted]` 出现。

当前允许的已知命中：

- `tests\test_deployment_templates.py` 中的敏感片段断言。
- `tests\test_tool_artifacts.py` 等脱敏单测中的假密钥、假 token、假密码 fixture。
- `tests\fixtures\rag_eval_cases.json`、`tests\fixtures\login_rag_eval_cases.json` 和 `tests\fixtures\refund_rag_eval_cases.json` 中的业务 fixture 文本。

运行环境检查：

- `.env/config.py` 不提交。
- `.env.runtime` 不提交。
- `.venv/`、`.model_cache/`、`data/`、`logs/`、`knowledge_export/` 不提交。
- 真实 API key 不进入 README、docs、tests、示例配置或提交记录。

## 3. 发布验收标准

功能验收：

- `/health` 可返回服务状态。
- `/ready` 或 `scripts/check_readiness.py` 可返回 ready。
- 同步生成接口仍可按原接口返回 `GenerateResponse`。
- 异步生成接口可返回 `job_id`，并可查询 `queued/running/succeeded/failed` 状态。
- RAG 文档可导入、查询、upsert、delete。
- 生成历史可查询列表和详情。
- 预算/质量门控失败可写入待处理列表。
- 门控记录可被 `approved` 或 `rejected`，重复处理返回 409。
- Excel 导出仍可用。
- pytest 导出可生成默认 skip 的自动化脚手架，也可生成登录 API adapter 示例。
- 覆盖率评估可返回未覆盖需求、缺失关键词和建议，并可把人工确认的缺口 upsert 到知识库。

工程验收：

- 全量测试通过。
- 测试 Agent 契约模块 mypy 类型检查通过。
- 前端 Vitest 和 Vite 构建通过。
- 文档能解释项目定位、架构、配置、部署和后续工作。
- 已知限制和后续工作有明确说明。
- Git 工作区干净。

## 4. 已知限制

- Redis/RQ 外部队列已接入；任务状态和生成历史写入当前数据库 backend。
- 默认 SQLite 适合单机和受控部署，不适合作为高并发多租户生产数据库；MySQL backend 已实现并通过 smoke，但尚未切为生产默认。
- 应用内限流是内存级限流，不能替代网关层限流。
- 当前 Reviewer 主要是本地规则，不是大模型评审。
- 当前需求覆盖率评估主要基于关键词匹配，适合作为缺口初筛；缺口沉淀需要人工确认，不替代需求评审。
- pytest 导出默认仍是模板能力；当前已提供登录 API adapter 示例，其他业务 API 或 UI adapter 仍需按项目补充。
- RAG 尚未接入 rerank、metadata filter 的完整查询策略和线上召回监控。
- 当前没有用户体系、项目级权限隔离、RBAC 和多知识库授权。
- 已有内部 metrics 和 Prometheus 告警规则模板，但还没有集中日志采集、正式告警落地、请求/LLM usage 聚合指标和分布式链路追踪。
- Docker 轻量 Redis/RQ smoke 已完成实机验证；完整 ML/RAG 镜像仍需要在网络稳定环境做生产构建验证。
- LangGraph backend 已完成最小服务级 smoke，并已切为默认 backend；`local` backend 仍可通过配置回退。

## 5. 不纳入本次发布

- Celery 或更严格的原子有界队列实现。
- MySQL 默认 backend 切换评估、更长时间稳定性和高并发验证；在完成多轮/多 worker 稳定性、恢复演练和容量验证前，不切为默认 backend。
- 深化 LangGraph checkpoint、interrupt、人审节点和 trace 能力。
- LangGraph checkpoint、interrupt、人审节点和可视化 trace 深度集成。
- 多用户权限系统。
- 生产级前端管理后台，包括多项目、多用户、权限和审计。
- 与禅道、TestRail、飞书多维表格等平台的正式 adapter。
- 公网 HTTPS 网关、WAF、集中监控和告警。

## 6. 后续工作

推荐顺序：

1. 生产数据库：补齐 MySQL 连接池参数、长时间稳定性验证、高并发验证，并评估是否切为默认 backend。
2. Docker 生产硬化：完整 ML/RAG 镜像构建验证、镜像体积和缓存策略；Compose 已默认使用 named volume，非 root bind mount 权限说明已补齐。
3. Agent 框架：在默认 LangGraph backend 上补齐 checkpoint、interrupt、人审节点和 trace 能力，并保留 `local` 回滚策略。
4. RAG 增强：增加 metadata filter、rerank、固定评估集和召回指标。
5. 可观测性：把内部 metrics 和告警规则接入正式监控系统，继续补请求量、失败率、LLM usage、成本和耗时分布。
6. 权限隔离：增加用户、项目、知识库权限和操作审计。
7. 测试落地：继续扩展退款等业务 API adapter，并把人工覆盖确认结果回流到固定评估集。
