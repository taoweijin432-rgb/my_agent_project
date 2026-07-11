# 测试执行 Agent 改造计划

## 1. 改造目标

目标是把当前“RAG Agent 测试用例生成器”升级为“需求到测试执行报告”的测试 Agent：

```text
读取需求 -> 生成测试计划 -> 选择并调用工具 -> 汇总执行结果 -> 生成报告 -> 用测评集持续评估
```

改造后的系统应支持：

- 读取 PRD、接口说明、用户故事、验收标准和已有知识库。
- 生成结构化测试计划，而不仅是测试用例列表。
- 根据测试计划选择工具执行，例如 HTTP 检查、pytest、Playwright、SQL 检查或人工步骤。
- 收集工具输出、日志、截图、退出码和产物路径。
- 汇总需求覆盖、失败原因、阻塞项、缺陷建议和下一步动作。
- 用固定测评集衡量计划质量、工具调用正确性和报告事实一致性。

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
| Evaluation Harness | 使用固定测评集评估计划、调用和报告质量 |

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
- 测评集先覆盖 5-10 条典型需求。

验收：

- 输入登录、退款等需求后能生成结构化计划。
- 每个计划步骤能关联需求点、测试类型、优先级、工具和成功标准。
- 单测覆盖 schema 校验和报告状态归并。

### 阶段 2：工具执行闭环

目标：让计划中的部分步骤能真实调用工具执行。

任务：

- 新增 Tool Adapter 接口。已开始：`app/services/tool_adapters.py` 提供 HTTP adapter MVP。
- 优先实现 HTTP adapter 和 pytest adapter。已完成：HTTP adapter 支持结构化 method/path/header/json/expected_status，不执行 shell，拒绝外部完整 URL；pytest adapter 支持安全相对路径、`-k`、`-m`、`--maxfail`、超时和非 shell 执行。
- 用现有异步任务队列执行工具任务。已开始：`app/services/tool_execution.py` 提供同步执行编排层，后续可挂入异步任务队列。
- 统一记录 `ToolRun`，保存 stdout/stderr、退出码、产物路径和耗时。已开始：HTTP adapter 和执行编排层统一返回 `ToolRun`。
- 汇总执行结果为报告。已开始：`app/services/test_report.py` 可将 `TestPlan + ToolRun[]` 汇总为 `TestExecutionReport`，并计算需求覆盖、缺陷和建议。
- 增加端到端 smoke。已完成：`tests/test_test_execution_smoke.py` 覆盖 HTTP step 执行、失败报告和 manual skipped 覆盖处理。
- 暴露内部执行 API。已完成：`POST /api/v1/test-plans/execute-step` 执行单个步骤，`POST /api/v1/test-plans/execute` 执行整份计划并返回报告；HTTP adapter 默认注册，pytest adapter 需要显式设置 `TEST_TOOL_PYTEST_ENABLED=true`。
- 增加异步执行 job。已完成：`POST /api/v1/test-plans/execution-jobs` 提交执行任务，列表和详情接口可查询 `queued/running/succeeded/failed`；默认使用 in-memory worker，本地和 RQ 模式下均支持 SQLite 持久化、stale running 恢复；`GENERATION_JOB_QUEUE_BACKEND=rq` 时可由 Redis/RQ worker 消费。
- 增加执行超时、命令白名单和工作目录限制。已开始：HTTP adapter 支持 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST`；pytest adapter 支持 `TEST_TOOL_PYTEST_ALLOWED_PATHS` 和超时。
- 增加工具执行 artifacts。已完成：`ToolArtifactStore` 将 HTTP 响应摘要和 pytest stdout/stderr 写入 `TEST_TOOL_ARTIFACT_DIR`，并通过 `ToolRun.artifact_paths` 返回证据路径；`scripts/cleanup_tool_artifacts.py` 可按 `TEST_TOOL_ARTIFACT_RETENTION_SECONDS` 清理过期 artifact。
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
- 前端新增计划详情、执行进度和报告查看。
- 支持报告导出为 Markdown 或 JSON。

验收：

- 报告只基于结构化执行结果生成。
- 报告能指出未执行、失败、阻塞和跳过的步骤。
- 前端能从计划进入执行，再进入报告。

### 阶段 4：测评集和质量门控

目标：让改造后的 Agent 有可持续评估能力。

任务：

- 建立 `tests/fixtures/test_agent_eval_cases.json`。
- 为每条样本定义期望需求覆盖、风险点、工具类型和报告关键事实。
- 新增评估脚本，输出计划覆盖率、工具选择正确率和报告事实一致率。
- 将评估脚本接入发布检查。

验收：

- 固定测评集可在 CI 或本地稳定运行。
- 评估结果能定位是计划问题、工具选择问题还是报告总结问题。

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
- 工具执行 artifact 落盘、单文件截断和过期清理已完成。
- 测试计划执行 job 已接入 Redis/RQ worker 模式，复用 `scripts/run_generation_worker.py` 监听同一队列。
- 测试 Agent 契约模块已接入 mypy 类型门禁，作为 release check 的默认步骤。

下一步建议补更细粒度的 headers/env 限制和 artifact 下载权限，再进入前端工作台接入。
