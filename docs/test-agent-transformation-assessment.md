# 测试执行 Agent 改造阶段评估

评估日期：2026-07-15

## 1. 阶段结论

当前项目已经从“测试用例生成器”推进到“测试执行 Agent MVP”：

```text
需求 -> 测试计划 -> 工具执行 -> ToolRun -> 执行报告 -> 异步 job 查询 -> 真实 LLM strict 测评 + 快速回归
```

这个闭环已经具备工程可验证性，但仍是受控环境 MVP，不是生产级测试执行平台。

## 2. 已具备闭环

### 2.1 需求到测试计划

已完成：

- `TestPlanGenerationRequest`
- `TestPlan`
- `TestPlanStep`
- 规则 planner：`TestPlanGenerator`
- LLM planner：`LLMTestPlanGenerator`
- Prompt：`build_test_plan_messages`
- API：`POST /api/v1/test-plans/generate`
- 固定评估：`scripts/evaluate_test_plan.py`
- 真实 LLM workflow 评估：`scripts/evaluate_test_agent_workflow.py --use-llm --strict-plan-tools --strict-plan-test-types --strict-http-headers`

当前能力：

- 默认可用规则 planner 稳定生成计划。
- 可显式启用真实 LLM；模型质量结论以真实 LLM strict workflow eval 为准。
- LLM 输出会经过 Pydantic schema 校验。
- 支持 fallback 控制。

### 2.2 工具执行

已完成：

- `HTTPToolAdapter`
- `PytestToolAdapter`
- `ToolExecutionService`
- API：
  - `POST /api/v1/test-plans/execute-step`
  - `POST /api/v1/test-plans/execute`

当前能力：

- HTTP adapter 默认可用。
- pytest adapter 已实现，但默认关闭。
- pytest adapter 只能执行配置允许路径下的安全相对路径，不走 shell，默认允许 `tests/`。
- `manual` 步骤返回 `skipped`。
- 未注册工具返回 `blocked`。

### 2.3 报告汇总

已完成：

- `TestExecutionReport`
- `build_execution_report`
- 需求覆盖计算
- defect 汇总
- recommendations 汇总

当前策略：

- 只有 `passed` 计入需求覆盖。
- `failed` 会生成 defect。
- `blocked` 会生成环境或 adapter 建议。
- `skipped` 不计入覆盖，避免把人工未执行步骤误判为已验证。

### 2.4 异步执行

已完成：

- `InMemoryTestPlanExecutionJobQueue`
- `scripts/check_test_plan_execution_queue.py`
- `scripts/smoke_test_plan_execution_worker.py`
- API：
  - `POST /api/v1/test-plans/execution-jobs`
  - `GET /api/v1/test-plans/execution-jobs`
  - `GET /api/v1/test-plans/execution-jobs/{job_id}`

当前能力：

- 支持 `queued/running/succeeded/failed`。
- worker 线程异步执行测试计划。
- 失败会记录结构化 error。
- `GENERATION_JOB_QUEUE_BACKEND=rq` 时可派发到 Redis/RQ worker，由 `scripts/run_generation_worker.py` 监听同一队列执行。

限制：

- 默认 `in_memory` backend 仍是进程内 worker，适合本地开发。
- SQLite store 下已持久化 job 状态、请求、报告和错误；启动时会把 stale running 任务标记为 failed。
- RQ 路径已补专门的队列观测脚本、worker smoke 和 MySQL profile 下的 RQ worker stability smoke；测试计划执行 job 状态已支持写入 MySQL `test_plan_execution_jobs` 表，更长时间稳定性验证仍建议保留。

### 2.5 测评集和真实 LLM 门禁

已完成：

- `tests/fixtures/test_plan_eval_cases.json`
- `scripts/evaluate_test_plan.py`
- 默认发布检查中的 `test-plan-eval`
- `scripts/evaluate_test_agent_workflow.py --use-llm` 真实 LLM workflow strict 门禁

当前指标：

- 工具选择命中率。
- 测试类型命中率。
- 风险关键词命中率。
- case pass rate。

定位：

- deterministic/固定测评集用于快速回归，不推荐用于判断真实模型约束效果。
- 真实 LLM strict workflow eval 才用于验证 Prompt、模型输出、adapter 契约归一化和报告门禁是否真正约束住当前模型。
- 2026-07-20 当前默认模型 `glm-4-flash` 已覆盖当前 18 个需求到报告样本：全量 strict eval 通过，所有质量门禁为 1.0，无 fallback、无 retry、无 timeout/429；`plan_generation.avg=28370.313ms`、`plan_generation.max=50612.814ms`。

## 3. 当前工程质量

优势：

- 模型边界清晰，`TestPlan`、`ToolRun`、`TestExecutionReport` 已成型。
- 真实 LLM 已通过 strict workflow eval 验证：当前默认模型能返回可执行 `TestPlan`，并通过工具执行、报告事实、原因分类、建议 grounding 和证据追溯门禁。
- 工具执行不依赖 shell 字符串，安全边界比直接命令执行更可控。
- API 和核心服务都有直接单测，不依赖 FastAPI `TestClient`。
- 测试计划、测试执行报告和端到端执行测评脚本已接入发布检查；真实 LLM planner/workflow 测评也已作为显式可选检查接入，后续迭代有真实模型门禁和快速回归基线。
- 测试 Agent 契约模块已接入 mypy 类型门禁，覆盖模型、工具 adapter、执行编排、执行 job、store、报告和 RQ worker。

主要限制：

- test plan execution job 已有 SQLite 持久化 MVP，并可通过 Redis/RQ worker 独立消费；队列观测脚本、worker smoke、runtime smoke、Redis/MySQL 短暂不可用演练和 Redis/RQ + MySQL worker 稳定性演练已补齐，覆盖 stale recovery、多 job、保留期清理、队列满背压、依赖故障检查和 artifact 产出，但更长时间稳定性验证仍建议保留。
- pytest adapter 已接入 stdout/stderr artifact 收集。
- HTTP adapter 已接入响应摘要 artifact 收集，并已支持 artifact 单文件截断、过期清理和受控下载；后续可继续扩展断言详情和结构化响应片段。
- adapter 入口已通过 `HTTPToolArgs`、`PytestToolArgs` 做工具参数强类型校验；`TestPlanStep.tool_args` 作为 LLM/API 公共字段仍保留 JSON object 形态。
- 默认发布检查已新增 `type-check-test-agent`，避免核心契约模块在后续迭代中发生类型漂移。
- 报告是确定性汇总，已支持 Markdown/JSON 导出；还没有 LLM 报告润色和更细粒度证据引用。
- 前端已接入测试计划生成、执行 job、报告查看和报告导出基础页面；仍不是生产级多项目管理后台。
- 工具 adapter 已具备配置级 base URL、headers、pytest path 和 pytest env allowlist，仍需要按部署环境配置具体目标。

## 4. 风险评估

| 风险 | 当前等级 | 说明 | 建议 |
| --- | --- | --- | --- |
| 任意工具执行风险 | 中 | pytest adapter 默认关闭，并受 allowed paths 限制 | 保持默认关闭，生产环境配置最小 allowed paths |
| SSRF 风险 | 中 | HTTP adapter 使用调用方提供 base URL，可配置 allowlist | 生产环境必须配置 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST` |
| 执行队列可观测性 | 低 | 测试计划执行 job 已补专门的队列观测脚本、worker smoke、queue alert 阈值检查和 MySQL 持久化路径 | 后续继续补更长时间运行验证 |
| 工具参数契约漂移 | 低 | adapter 入口已有强类型参数模型，但 planner 输出仍是通用 JSON object | 下一步可评估 discriminated union 或在 planner 后增加 plan validation gate |
| 报告幻觉 | 低 | 当前报告不调用 LLM | 后续 LLM 报告必须引用结构化证据 |
| 测评集过小 | 中 | 当前已覆盖计划生成、报告事实一致性、端到端执行、SQLite/in-memory runtime smoke、Redis/MySQL outage smoke、RQ worker stability smoke 和 18 条真实 LLM workflow strict 样本，但真实业务域仍不够多 | 从登录、退款、权限、UI、数据库和真实执行环境继续扩展，并优先用真实 LLM strict eval 验证 |
| 模型切换质量漂移 | 中 | 当前模型下无 timeout/429，之前慢调用更像模型或上游状态差异 | 模型切换后重新跑真实 LLM strict eval，并记录 benchmark history |

## 5. 下一阶段优先级

### P1：执行 job worker 化

目标：

- 复用现有 Redis/RQ worker 模式。已完成。
- 让测试计划执行 job 可由独立 worker 消费。已完成。
- 保留现有 stale running job 恢复语义。已完成。

验收：

- 提交测试计划执行 job 后，API/worker 重启仍可查询状态。已具备 SQLite 持久化路径。
- stale running job 能被标记为 failed。已具备。

### P1：工具执行安全收紧

目标：

- 按部署环境配置 HTTP base URL allowlist。
- 按部署环境配置 pytest allowed path allowlist。
- 限制 headers 和环境变量。已完成。
- artifact 已写入受控目录，并支持单文件截断、按保留期清理和受控下载。

验收：

- 非 allowlist base URL 被拒绝。已具备配置能力。
- 非 allowlist pytest 路径被拒绝。已具备配置能力。
- 非 allowlist HTTP header 被拒绝。已具备。
- pytest 子进程只接收 allowlist 环境变量。已具备。
- artifact 下载只能读取 artifact 根目录内文件。已具备。
- 过期 artifact 可通过清理脚本删除。已具备。
- adapter 不读取或泄漏本地敏感环境变量。已具备。

### P2：前端工作台接入

目标：

- 新增测试计划生成页。已完成基础接入。
- 新增执行 job 列表和详情。已完成基础接入。
- 新增报告视图。已完成基础接入。
- 新增报告导出入口。已完成基础接入。

验收：

- 前端可完成需求输入、生成计划、提交执行、查看报告并导出 Markdown/JSON。已具备基础路径。

### P2：报告增强

目标：

- 引入 LLM 报告总结，但只允许引用结构化 `ToolRun`、defects、coverage 和 artifacts。
- 支持 Markdown/JSON 导出。已完成。
- 增加更明确的失败证据映射和 artifact 链接展示。

验收：

- 报告能清楚区分 passed、failed、blocked、skipped。
- 报告中的失败结论能追溯到具体 `ToolRun`。
- 导出的报告不引入结构化执行结果之外的新事实。

## 6. 阶段判断

当前改造已经完成“Agent 测试执行闭环”的 MVP：

- 能生成计划。
- 能执行 HTTP/pytest 类工具。
- 能汇总报告。
- 能导出报告。
- 能异步提交和查询。
- 能用固定测评集做基础质量回归。
- 能用真实 LLM strict workflow eval 验证模型输出是否真正受 Prompt、schema、adapter 和报告门禁约束。

下一步不建议继续堆新 adapter，也不建议用离线测评替代真实模型判断。优先扩展真实业务 workflow 样本、真实 LLM strict 门禁常态化、模型切换 benchmark history 和更长时长稳定性验证。
