# 测试执行 Agent 改造阶段评估

评估日期：2026-07-10

## 1. 阶段结论

当前项目已经从“测试用例生成器”推进到“测试执行 Agent MVP”：

```text
需求 -> 测试计划 -> 工具执行 -> ToolRun -> 执行报告 -> 异步 job 查询 -> 固定测评
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

当前能力：

- 默认可用规则 planner 稳定生成计划。
- 可显式启用真实 LLM。
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
- RQ 路径还需要补专门的队列观测和长时间稳定性验证。

### 2.5 测评集

已完成：

- `tests/fixtures/test_plan_eval_cases.json`
- `scripts/evaluate_test_plan.py`
- 默认发布检查中的 `test-plan-eval`

当前指标：

- 工具选择命中率。
- 测试类型命中率。
- 风险关键词命中率。
- case pass rate。

## 3. 当前工程质量

优势：

- 模型边界清晰，`TestPlan`、`ToolRun`、`TestExecutionReport` 已成型。
- 真实 LLM 已验证可返回合规 `TestPlan`。
- 工具执行不依赖 shell 字符串，安全边界比直接命令执行更可控。
- API 和核心服务都有直接单测，不依赖 FastAPI `TestClient`。
- 测评脚本已接入发布检查，后续迭代有回归基线。
- 测试 Agent 契约模块已接入 mypy 类型门禁，覆盖模型、工具 adapter、执行编排、执行 job、store、报告和 RQ worker。

主要限制：

- test plan execution job 已有 SQLite 持久化 MVP，并可通过 Redis/RQ worker 独立消费；后续还需要补队列观测和长时间稳定性验证。
- pytest adapter 已接入 stdout/stderr artifact 收集。
- HTTP adapter 已接入响应摘要 artifact 收集，并已支持 artifact 单文件截断和过期清理；后续可继续扩展断言详情、结构化响应片段和下载接口。
- adapter 入口已通过 `HTTPToolArgs`、`PytestToolArgs` 做工具参数强类型校验；`TestPlanStep.tool_args` 作为 LLM/API 公共字段仍保留 JSON object 形态。
- 默认发布检查已新增 `type-check-test-agent`，避免核心契约模块在后续迭代中发生类型漂移。
- 报告是确定性汇总，还没有 LLM 报告润色和证据引用。
- 前端还没有测试计划生成、执行和报告页面。
- 工具 adapter 已具备配置级 allowlist，仍需要按部署环境配置具体目标。

## 4. 风险评估

| 风险 | 当前等级 | 说明 | 建议 |
| --- | --- | --- | --- |
| 任意工具执行风险 | 中 | pytest adapter 默认关闭，并受 allowed paths 限制 | 保持默认关闭，生产环境配置最小 allowed paths |
| SSRF 风险 | 中 | HTTP adapter 使用调用方提供 base URL，可配置 allowlist | 生产环境必须配置 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST` |
| 执行队列可观测性不足 | 中 | 测试计划执行 job 已可走 Redis/RQ worker，但还没有专门的队列观测脚本和长稳 smoke | 复用或扩展现有队列检查脚本，补 worker 长时间运行验证 |
| 工具参数契约漂移 | 低 | adapter 入口已有强类型参数模型，但 planner 输出仍是通用 JSON object | 下一步可评估 discriminated union 或在 planner 后增加 plan validation gate |
| 报告幻觉 | 低 | 当前报告不调用 LLM | 后续 LLM 报告必须引用结构化证据 |
| 测评集过小 | 中 | 当前只有首批样本 | 从登录、退款、权限、UI、数据库继续扩展 |

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
- 限制 headers 和环境变量。
- artifact 已写入受控目录，并支持单文件截断和按保留期清理。

验收：

- 非 allowlist base URL 被拒绝。已具备配置能力。
- 非 allowlist pytest 路径被拒绝。已具备配置能力。
- 过期 artifact 可通过清理脚本删除。已具备。
- adapter 不读取或泄漏本地敏感环境变量。

### P2：前端工作台接入

目标：

- 新增测试计划生成页。
- 新增执行 job 列表和详情。
- 新增报告视图。

验收：

- 前端可完成需求输入、生成计划、提交执行、查看报告。

### P2：报告增强

目标：

- 引入 LLM 报告总结，但只允许引用结构化 `ToolRun`、defects、coverage 和 artifacts。
- 支持 Markdown 导出。

验收：

- 报告能清楚区分 passed、failed、blocked、skipped。
- 报告中的失败结论能追溯到具体 `ToolRun`。

## 6. 阶段判断

当前改造已经完成“Agent 测试执行闭环”的 MVP：

- 能生成计划。
- 能执行 HTTP/pytest 类工具。
- 能汇总报告。
- 能异步提交和查询。
- 能用固定测评集做基础质量回归。

下一步不建议继续堆新 adapter。优先补更细粒度的 headers、环境变量、artifact 下载权限限制，以及测试计划执行队列观测。
