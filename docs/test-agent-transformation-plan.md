# 测试执行 Agent 改造计划

## 1. 改造目标

目标是把当前“RAG Agent 测试用例生成器”升级为“需求到测试执行报告”的测试 Agent：

```text
读取需求 -> 生成测试计划 -> 选择并调用工具 -> 汇总执行结果 -> 生成报告 -> 用真实 LLM strict 测评和快速回归持续评估
```

改造后的系统应支持：

- 读取 PRD、接口说明、用户故事、验收标准和已有知识库。
- 生成结构化测试计划，而不仅是测试用例列表。
- 根据测试计划选择工具执行，例如 HTTP 检查、pytest、Playwright、SQL 检查或人工步骤。
- 收集工具输出、日志、截图、退出码和产物路径。
- 汇总需求覆盖、失败原因、阻塞项、缺陷建议和下一步动作。
- 用真实 LLM strict workflow eval 衡量模型约束效果，用 deterministic/固定测评集做快速回归保护。

## 2. 可行性结论

可行性高。

当前项目已经具备以下基础：

- RAG 知识库导入、检索和固定评估。
- Agent workflow、Reviewer、质量门控和 usage 估算。
- 同步/异步生成接口、Redis/RQ 队列和任务状态持久化。
- 生成历史、门控审批、覆盖率评估和前端工作台。
- 发布检查、readiness、队列观测和 Docker/Compose 基线。

因此改造重点不是重写系统，而是新增三层能力：

1. 测试计划结构化模型。
2. 工具执行 adapter 和安全边界。
3. 测评集与报告质量评估。

## 3. 目标架构

```text
Requirement Ingestion
  -> Requirement Analyzer
  -> RAG Context Retrieval
  -> Test Plan Planner
  -> Tool Selection
  -> Tool Execution Queue
  -> Result Normalizer
  -> Report Summarizer
  -> Evaluation Harness
```

模块职责：

| 模块 | 职责 |
| --- | --- |
| Requirement Ingestion | 读取需求文本、文档、知识库片段和历史记录 |
| Requirement Analyzer | 抽取需求点、验收标准、风险和不明确项 |
| Test Plan Planner | 生成范围、策略、步骤、优先级、工具和通过标准 |
| Tool Adapter | 封装 pytest、Playwright、HTTP、SQL 等工具调用 |
| Execution Queue | 使用现有异步任务队列承载长时间执行 |
| Result Normalizer | 将退出码、日志、截图、JUnit 等产物归一化 |
| Report Summarizer | 基于结构化结果生成报告摘要，不自由编造 |
| Evaluation Harness | 使用真实 LLM strict workflow eval 评估模型输出约束效果，使用固定测评集做快速回归 |

## 4. 数据模型规划

第一批模型已从 `app/models/test_plan.py` 开始：

- `TestPlan`：一次需求分析后的测试计划。
- `TestPlanStep`：计划中的可执行或人工测试步骤。
- `ToolRun`：一次工具调用结果。
- `TestExecutionReport`：最终执行报告。
- `summarize_report_status`：将多次工具执行状态归并为报告状态。

后续可继续补充：

- `RequirementAnalysisResult`：需求解析结果。
- `ToolInvocationRequest`：工具调用请求。
- `ToolInvocationResult`：工具调用原始结果。
- `EvaluationCase`：测评集单条样本。
- `EvaluationResult`：测评运行结果。

## 5. 分阶段实施

### 阶段 1：测试计划 MVP

目标：先让系统能稳定生成结构化测试计划。

任务：

- 固化 `TestPlan`、`TestPlanStep`、`TestExecutionReport` schema。
- 新增“需求 -> 测试计划”的 service。
- 为测试计划生成新增 Prompt 和单测。
- 前端新增测试计划预览区域。
- 测评集先覆盖 10+ 条典型需求。

验收：

- 输入登录、退款等需求后能生成结构化计划。
- 每个计划步骤能关联需求点、测试类型、优先级、工具和成功标准。
- 单测覆盖 schema 校验和报告状态归并。

### 阶段 2：工具执行闭环

目标：让计划中的部分步骤能真实调用工具执行。

任务：

- 新增 Tool Adapter 接口。已开始：`app/services/tool_adapters.py` 提供 HTTP adapter MVP。
- 优先实现 HTTP adapter 和 pytest adapter。已完成：HTTP adapter 支持结构化 method/path/header/json/expected_status/json_assertions，不执行 shell，拒绝外部完整 URL，并可用声明式 JSON 字段断言校验响应 body；pytest adapter 支持安全相对路径、`-k`、`-m`、`--maxfail`、超时和非 shell 执行。
- 用现有异步任务队列执行工具任务。已开始：`app/services/tool_execution.py` 提供同步执行编排层，后续可挂入异步任务队列。
- 统一记录 `ToolRun`，保存 stdout/stderr、退出码、产物路径和耗时。已开始：HTTP adapter 和执行编排层统一返回 `ToolRun`。
- 汇总执行结果为报告。已开始：`app/services/test_report.py` 可将 `TestPlan + ToolRun[]` 汇总为 `TestExecutionReport`，并计算需求覆盖、缺陷和建议。
- 增加端到端 smoke。已完成：`tests/test_test_execution_smoke.py` 覆盖 HTTP step 执行、失败报告和 manual skipped 覆盖处理。
- 暴露内部执行 API。已完成：`POST /api/v1/test-plans/execute-step` 执行单个步骤，`POST /api/v1/test-plans/execute` 执行整份计划并返回报告；HTTP adapter 默认注册，pytest adapter 需要显式设置 `TEST_TOOL_PYTEST_ENABLED=true`。
- 增加异步执行 job。已完成：`POST /api/v1/test-plans/execution-jobs` 提交执行任务，列表和详情接口可查询 `queued/running/succeeded/failed`；默认使用 in-memory worker，本地和 RQ 模式下均支持 SQLite 持久化、stale running 恢复；`GENERATION_JOB_QUEUE_BACKEND=rq` 时可由 Redis/RQ worker 消费。
- 增加执行超时、命令白名单、headers 白名单和工作目录限制。已完成：HTTP adapter 支持 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST` 和 `TEST_TOOL_HTTP_ALLOWED_HEADERS`；pytest adapter 支持 `TEST_TOOL_PYTEST_ALLOWED_PATHS`、`TEST_TOOL_PYTEST_TIMEOUT_SECONDS` 和 `TEST_TOOL_PYTEST_ENV_ALLOWLIST`。
- 增加工具执行 artifacts。已完成：`ToolArtifactStore` 将 HTTP 响应摘要和 pytest stdout/stderr 写入 `TEST_TOOL_ARTIFACT_DIR`，并通过 `ToolRun.artifact_paths` 返回证据路径；`scripts/cleanup_tool_artifacts.py` 可按 `TEST_TOOL_ARTIFACT_RETENTION_SECONDS` 清理过期 artifact；`GET /api/v1/test-plans/artifacts/{artifact_path}` 只允许下载 artifact 根目录内的文件。
- 收紧工具参数契约。已完成：新增 `HTTPToolArgs` 和 `PytestToolArgs`，adapter 入口先做强类型校验，再执行 HTTP/pytest 工具；测试计划执行 job status 已收敛为枚举。
- 增加测试 Agent 契约模块类型门禁。已完成：默认发布检查新增 `type-check-test-agent`，使用 mypy 覆盖测试计划模型、工具 adapter、执行编排、执行 job、store、报告和 RQ worker。

验收：

- 能执行一个 HTTP 检查计划。
- 能执行一个 pytest adapter 计划。
- 失败时报告能展示失败工具、失败步骤和关键日志摘要。

### 阶段 3：报告汇总和前端工作台

目标：把工具执行结果汇总成可读报告。

任务：

- 新增 `TestExecutionReport` 生成 service。
- 汇总需求覆盖、通过/失败/阻塞步骤、缺陷建议和下一步动作。
- 前端新增计划详情、执行进度和报告查看。已完成基础接入：`frontend/src/components/TestPlanPanel.tsx` 支持生成计划、同步执行、提交执行 job、查看任务详情和执行报告。
- 支持报告导出为 Markdown 或 JSON。已完成：`POST /api/v1/test-plans/reports/export` 可将结构化 `TestExecutionReport` 导出为 Markdown 或 JSON，前端报告视图提供下载入口。

验收：

- 报告只基于结构化执行结果生成。
- 报告能指出未执行、失败、阻塞和跳过的步骤。
- 前端能从计划进入执行，再进入报告，并导出报告。已具备基础工作台路径。

### 阶段 4：测评集和质量门控

目标：让改造后的 Agent 有可持续评估能力。

任务：

- 建立 `tests/fixtures/test_agent_eval_cases.json`。
- 为每条样本定义期望需求覆盖、风险点、工具类型和报告关键事实。
- 新增评估脚本，输出计划覆盖率、工具选择正确率和报告事实一致率。
- 将评估脚本接入发布检查。
- 已开始：`tests/fixtures/test_plan_eval_cases.json` 扩展到登录、退款、鉴权、审计 SQL 和异步状态场景；`tests/fixtures/test_report_eval_cases.json` 覆盖 failed、incomplete、blocked 报告事实，并要求报告建议绑定 failed/blocked/skipped 的具体步骤和明确 next-action 动词；`tests/fixtures/test_execution_eval_cases.json` 覆盖 HTTP 通过/失败、pytest 通过、HTTP+pytest 混合失败、退款多步骤业务流和 HTTP header 权限阻塞执行链路；`scripts/evaluate_test_report.py` 与 `scripts/evaluate_test_execution.py` 已接入默认发布检查。

验收：

- 固定测评集可在 CI 或本地稳定运行，但只作为快速回归保护，不作为模型质量结论。
- 模型质量结论必须来自真实 LLM strict workflow eval，且校验对象必须是实际 generator 输出的 `TestPlan`。
- 评估结果能定位是计划问题、工具选择问题还是报告总结问题。
- 报告评估能校验 status、summary fact quality、需求覆盖、defect step grounding、reason classification、reason-aware recommendation、recommendation step grounding、next-action quality、evidence artifact/output trace quality 和 Markdown/JSON 导出事实片段。
- 执行评估能真实走 adapter、执行编排和报告构建，并校验 tool status、report status、coverage、defect grounding、blocked grounding 和执行证据片段。
- Workflow 评估能从需求样本开始，经过规则 planner、工具执行和报告构建，校验 plan 工具选择、步骤数、风险关键词、执行状态、摘要事实一致性、覆盖率、缺陷归因、原因分类、原因感知建议、建议 grounding、next-action quality、证据 artifact/output 可追溯性和证据片段。

## 6. 工具 Adapter 设计原则

工具执行必须通过 adapter，而不是让 LLM 直接拼命令执行。

建议接口：

```python
class ToolAdapter:
    tool: TestToolType

    def validate(self, request: ToolInvocationRequest) -> None:
        ...

    def run(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        ...
```

约束：

- adapter 白名单注册。
- 命令参数结构化，不接受任意 shell 字符串。
- 每次执行有超时。
- 每次执行有独立工作目录。
- 产物只能写入指定 artifacts 目录。
- 环境变量显式传入，不继承敏感本地环境。

## 7. 测评集设计

测评集应覆盖三类质量：

| 类型 | 评估内容 |
| --- | --- |
| 计划质量 | 需求点覆盖、风险识别、测试类型和优先级是否合理 |
| 工具调用质量 | 是否选择正确工具、参数是否安全、步骤顺序是否可执行 |
| 报告质量 | 是否忠实引用执行结果、是否区分失败/阻塞/跳过 |

建议初始样本：

- 登录成功和失败路径。
- 权限不足。
- Token 过期。
- 退款幂等。
- 退款风控拦截。
- 需要人工确认的高风险变更。

## 8. 主要风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| LLM 生成不可执行计划 | 工具调用失败 | schema 校验、计划门控、测评集 |
| 工具执行越权 | 安全风险 | adapter 白名单、目录限制、命令结构化 |
| 报告幻觉 | 错误结论 | 报告只引用 `ToolRun` 和结构化结果 |
| 环境不稳定 | 假失败增多 | 区分 `failed` 和 `blocked` |
| 测评集过小 | 质量判断失真 | 从登录、退款逐步扩展 |

## 9. 当前进度和下一步

阶段 1 已完成：

1. 为 `app/models/test_plan.py` 补齐模型单测。已完成：`tests/test_test_plan_models.py`。
2. 新增 `TestPlanGenerator` service，将需求和 RAG 上下文转成 `TestPlan`。已完成：`app/services/test_plan_generator.py` 提供确定性 MVP，不调用真实 LLM。
3. 新增最小 Prompt 和 fixture。已完成：`build_test_plan_messages` 支持 JSON mode 测试计划 Prompt，`tests/fixtures/test_plan_eval_cases.json` 提供首批计划测评样本。
4. 新增测试计划测评脚本。已完成：`scripts/evaluate_test_plan.py` 输出工具选择、测试类型和风险关键词命中率，并已接入默认发布检查。
5. 暴露测试计划生成 API。已完成：`POST /api/v1/test-plans/generate` 默认使用规则 planner，可通过 `use_llm=true` 使用真实 LLM，并支持 fallback 控制。

阶段 2 已开始：

- HTTP adapter MVP 已完成。
- 同步执行编排层已完成。
- `TestPlan + ToolRun[] -> TestExecutionReport` 报告构建已完成。
- `POST /api/v1/test-plans/execute-step` 和 `POST /api/v1/test-plans/execute` 已完成。
- `POST /api/v1/test-plans/execution-jobs` 和查询接口已完成，SQLite backend 下已具备持久化 MVP 和 stale running 恢复。
- HTTP base URL allowlist 和 pytest allowed paths 已完成配置级约束。
- 工具执行 artifact 落盘、单文件截断、过期清理和受控下载已完成。
- 测试计划执行 job 已接入 Redis/RQ worker 模式，复用 `scripts/run_generation_worker.py` 监听同一队列。
- 测试计划执行队列观测和 worker smoke 已完成：`scripts/check_test_plan_execution_queue.py` 按 job function 过滤共享队列，`scripts/smoke_test_plan_execution_worker.py` 验证多 job 连续执行和 stale 恢复。
- 测试计划执行 runtime smoke 已完成：`scripts/smoke_test_plan_execution_runtime.py` 验证 SQLite job 保留期清理、in-memory 队列满背压和 worker 多任务稳定性。
- Redis/MySQL 短暂不可用恢复演练已完成可选入口：`scripts/smoke_runtime_dependency_outage.py` 会暂停 Redis/MySQL，验证队列检查明确失败，再恢复服务并验证检查通过；`scripts/run_release_checks.py --include-runtime-outage-smoke` 可显式触发。
- Redis/RQ worker 稳定性演练已完成可选入口：`scripts/smoke_rq_mysql_worker_stability.py` 会在 MySQL profile 环境中启动临时 worker，提交多条 pytest adapter 执行 job，校验 job 终态、passed/failed 报告混合结果和 artifact；`scripts/run_release_checks.py --include-rq-mysql-worker-stability-smoke` 可显式触发。`DATABASE_BACKEND=mysql` 时，测试计划执行 job 状态写入 MySQL `test_plan_execution_jobs` 表。该脚本已支持 `--rounds`、`--jobs-per-round` 和 `--worker-count`，用于更长时长、多轮、多 worker 稳定性验证。
- 队列 metrics/alert 阈值检查已完成可选入口：`scripts/check_queue_alerts.py` 聚合生成队列和测试计划执行队列的 `metrics`/`alerts`，支持 active jobs、RQ queued/started/failed、worker heartbeat 和 require-worker 阈值；`scripts/run_release_checks.py --include-queue-alert-check` 可显式触发。
- 测试 Agent 契约模块已接入 mypy 类型门禁，作为 release check 的默认步骤。
- 前端测试计划工作台已完成基础接入：新增侧边栏“测试计划”，覆盖需求输入、计划生成、同步执行、执行 job 提交/查询和报告展示。
- 报告导出已完成：后端支持 Markdown/JSON 导出，前端执行报告区可下载 `.md` 或 `.json` 文件。

真实 LLM planner 可选测评路径已接入：`scripts/run_release_checks.py --include-llm-test-plan-eval` 会运行 `scripts/evaluate_test_plan.py --use-llm`，且不启用 deterministic fallback。真实 LLM workflow 可选测评路径也已接入：`scripts/run_release_checks.py --include-llm-workflow-eval` 会运行 `scripts/evaluate_test_agent_workflow.py --use-llm --concurrency 1 --case-delay-seconds 2`，验证真实模型生成计划后是否仍能通过工具执行和报告门禁；workflow eval 会先校验 `tool_args` schema，并输出 `failure_codes` 和 `failure_reasons`，用于定位失败发生在工具参数、计划工具、测试类型、风险关键词、执行状态、摘要事实一致性、覆盖率、缺陷归因、原因分类、原因感知建议、建议 grounding、next-action 质量、证据 artifact 可追溯性或证据片段。workflow eval 已新增 strict 模式：`--strict-plan-tools`、`--strict-plan-test-types` 和 `--strict-http-headers` 可把集合包含检查升级为精确匹配，并检查 HTTP header 值质量。后续不推荐用离线/deterministic 测评判断模型约束效果；它们只用于快速发现契约回归。真实 LLM workflow 延迟 benchmark 已接入：`scripts/run_release_checks.py --include-llm-workflow-benchmark` 会运行不启用缓存和 fallback 的真实模型调用，用 `timing_ms` 建立 `total` 与 `plan_generation` 的慢调用基线，并把 summary 追加写入本地 `data/llm-workflow-benchmark-history.jsonl`。

workflow eval 的校验对象必须是实际 generator 输出的 `TestPlan`。默认 release check 校验规则 planner 的真实输出；`--use-llm` 校验真实 LLM 输出；不使用 fake generator 或模拟计划替代门禁结论。LLM planner 已增加输出契约归一化：HTTP 参数会映射到真实 adapter 接受的 `method`、`path`、`expected_status`、`json_assertions` 等字段，并从需求原文补齐明确的 HTTP 方法、路径、状态码和 JSON 字段断言；LLM 生成的 header 会按安全白名单过滤，避免 `Authorization`、Cookie、Token、API-Key 等密钥类 header 进入执行层；存在结构化需求时，`test_types` 以需求文本推断结果为准，避免真实模型额外输出 `boundary`、`security` 等类型导致 strict 评估漂移。真实 LLM workflow eval 已支持 `--concurrency`、`--case-id`、`--case-slice` 和 `--case-delay-seconds`，开发调试可用 `--use-cache` 复用真实模型历史输出，发布前可用 `--refresh-cache` 强制重新请求真实模型并覆盖缓存。2026-07-15 使用 `glm-4-flash` 完成当前 15 个样本的真实 LLM strict 覆盖：原 11 个样本全量 strict eval 与新增 4 个真实业务样本在 `json_assertions` 新契约下分批 strict eval 均通过，`case_pass_rate=1.0`，所有质量门禁为 1.0，无 fallback、无 retry、无 timeout/429；新增 4 个样本 `plan_generation.avg=29567.073ms`、`plan_generation.max=35863.873ms`。当前工程结论是模型输出契约已经可被真实 strict 门禁约束住；之前长耗时更像是模型或上游状态差异，不应泛化为当前方案缺陷。后续每次切换模型都要重新跑真实 LLM strict workflow eval，并用 benchmark history 对比耗时、timeout、retry 和 429。workflow job 已补充非敏感 LLM 调用观测：`result.timing.stages[].details.llm` 记录模型、base URL、timeout/retry 配置、backoff 配置、attempt/retry 次数、每次 attempt 耗时和错误类别，不记录 API key、prompt、业务输入或模型原始响应。workflow eval summary 已汇总 `llm_observability`，前端 workflow job 详情页已展示 LLM 尝试、重试、总耗时、缓存状态、最后状态和 fallback 使用情况。LLM retry 策略已支持 `LLM_RETRY_BACKOFF_SECONDS` 指数 backoff，429 会记录为 `rate_limited` 并在 retry 预算内重试，除 429 外的 `http_4xx` 不会浪费 retry 预算。

生产调用异步化已完成后端、前端和 Docker/RQ + MySQL 实机验证基线：`POST /api/v1/test-agent/workflow-jobs` 接收 `TestPlanGenerationRequest + http_base_url`，后台 job 依次执行真实/规则 planner、工具 adapter 和报告汇总；列表和详情接口可查询 `queued/running/succeeded/failed`、生成的 `TestPlan`、`TestExecutionReport` 和 `job.timing`。该路径复用现有 in-memory/RQ 队列、SQLite/MySQL 持久化和 stale running 恢复；前端测试计划工作台已支持提交完整 workflow、查看列表/详情、轮询活跃任务并回填 `result.plan`/`result.report`。`scripts/smoke_test_agent_workflow_rq_mysql.py` 会在 Docker Compose MySQL profile 下启动/复用 API、Redis、MySQL 和临时 RQ worker，提交 workflow job 并验证报告、artifact、需求覆盖、队列 alert、耗时汇总和吞吐汇总；可用 `--fail-over-max-queue-wait-ms` 和 `--fail-under-throughput-jobs-per-second` 设置吞吐门禁。

当前所处阶段：

- 阶段 1 测试计划 MVP 已完成。
- 阶段 2 工具执行闭环的核心链路已完成，当前在做 Redis/RQ + MySQL 执行稳定性和 workflow job 观测收尾。
- 阶段 3 报告汇总和前端工作台已有基线能力，“需求到报告”的 workflow job 已接入前端提交、轮询和结果回填，并通过 Docker/RQ + MySQL 实机 smoke；真实 LLM 长耗时观测字段、attempt 级调用 metrics、错误分类 retry/backoff、阶段失败码、延迟 benchmark 入口、JSONL 历史记录、strict 测评模式、eval summary 汇总、前端详情展示、worker 吞吐 summary 和吞吐阈值门禁已接入，后续继续补更多异常组合和业务视角报告质量。
- 阶段 4 测评集和质量门控已启动，执行结果测评集已扩展到退款业务流和 header 权限阻塞场景，并新增 blocked grounding 指标；`scripts/evaluate_test_agent_workflow.py` 已接入需求到报告的端到端 workflow 评估，当前覆盖退款失败审计、权限/鉴权失败、异步队列状态超时、支付对账幂等冲突、库存预占锁定异常、通知重试失败、文件导出越权下载、用户资料参数校验失败、退款金额不一致、异步终态不一致、结账前置失败、支付回调幂等冲突、pytest 断言失败、SQL adapter 缺失和人工确认未执行 15 条链路；退款金额不一致和异步终态不一致已从状态码间接表达升级为 `json_assertions` body 字段断言。报告建议已要求绑定 failed/blocked/skipped 的具体 step，并把 `summary_fact_quality_rate`、`reason_classification_rate`、`reason_aware_recommendation_rate`、`recommendation_grounding_rate`、`next_action_quality_rate` 和 `evidence_artifact_quality_rate` 接入 report/workflow eval 与 release checklist；原因分类已从通用 `http_status_mismatch` 细化到 `timeout`、`permission_denied`、`permission_not_enforced`、`conflict`、`upstream_unavailable`、`auth_failure`、`validation_error`、`response_assertion_mismatch`、`adapter_missing`、`assertion_mismatch`、`manual_confirmation_required` 等类型，建议也会按原因分类给出差异化动作；真实 LLM workflow strict 门禁已覆盖当前 15 条样本，并提供失败诊断 code、并发执行、真实输出缓存和 strict 质量模式，release checklist 已补 dry-run 模板和 failure code 解读；真实模型生成的计划会经过 adapter 契约归一化后再进入执行/报告评估；后续重点是扩展真实业务域样本、常态化真实 LLM 强门禁和持续记录模型切换后的耗时趋势。

后续路线：

1. 扩展阶段 2 收尾：测试计划执行 job 和测试 Agent workflow job 已具备多轮、多 worker 的 RQ + MySQL 稳定性 smoke，确保每轮执行后无 active job、无 RQ failed、无 MySQL/RQ 状态不一致；后续补更长时长、更高并发和异常恢复组合演练。
2. 继续扩展阶段 4 测评集：在现有退款、权限/鉴权、异步队列、支付对账、库存预占、通知重试、文件导出、参数校验失败、pytest 断言失败、SQL adapter 缺失和人工确认 workflow，以及执行退款业务流和 header 权限阻塞样本之外，继续增加更多真实业务需求样本，覆盖需求解析、计划生成、工具执行、报告汇总和失败归因。
3. 持续真实 LLM 验证路径：模型质量结论以 `--use-llm` strict workflow eval 为准；deterministic 路径只保留为快速回归保护，不推荐用于判断真实模型约束效果。下一步重点不是证明真实 LLM 能否跑通，而是把真实强门禁做成可持续机制：分批、限速、缓存复用、发布前 refresh、超时/重试、后台 job 分阶段可见性和 benchmark 趋势。
4. 强化报告质量：summary fact quality、覆盖率、缺陷归因、原因分类、原因感知建议、blocked grounding、recommendation grounding、next-action quality 和 evidence artifact/output trace quality 已进入可量化评估；HTTP 504/403/409/422/5xx、pytest assertion、adapter missing 和 manual skipped 等常见失败/阻塞/跳过已细分原因分类，并驱动差异化建议；后续继续把更多业务域原因类别和跨样本报告稳定性纳入门禁。
5. 评估默认 MySQL backend：在完成长时稳定性和高并发验证前，不把 MySQL smoke 通过等同于生产默认切换条件。
6. 补齐 workflow job 的生产配套：前端提交/轮询/结果回填、队列观测脚本、queue alert 阈值、Docker/RQ + MySQL 实机 smoke、首批耗时观测、阶段失败码、真实 LLM benchmark 入口和 JSONL 历史记录已完成；下一步把重试策略和 worker 处理能力纳入观测。
