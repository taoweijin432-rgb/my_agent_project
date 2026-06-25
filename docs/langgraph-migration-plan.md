# LangGraph 迁移评估

最后更新：2026-06-24

## 1. 结论

当前生成链路已完成 LangGraph-first 切换。LangGraph 是默认编排 backend，local backend 保留为 fallback 和行为对照。

当前状态：

- 已新增 `AGENT_WORKFLOW_BACKEND` 配置，默认 `langgraph`。
- 已新增 `GenerationWorkflowRunner` 抽象。
- 已把现有本地状态机封装为 `LocalGenerationWorkflowRunner`。
- 已新增 `LangGraphGenerationWorkflowRunner` 动态入口；未安装 LangGraph 时会明确报错。
- 基础依赖和轻量 smoke 依赖均已包含 LangGraph，`requirements-langgraph.txt` 保留为兼容入口。
- 当前虚拟环境已安装 LangGraph 依赖，并完成真实 `langgraph` backend 生成器行为测试。
- 默认 backend 已切到 `langgraph`；Docker 轻量 smoke 也默认安装并启用 LangGraph。

推荐路径：

1. 保留现有 `TestCaseGenerator.generate()` 对外行为。
2. 复用现有节点函数和 `GenerationWorkflowState`。
3. 保留可切换 backend：`AGENT_WORKFLOW_BACKEND=local|langgraph`。
4. 第一阶段让 LangGraph 只负责编排，不改变 Prompt、RAG、Reviewer、门控、异常和历史落库语义。
5. 保留 `local` backend 作为回滚路径，后续再深化 checkpoint、interrupt 和 trace。

阶段评估：可以进入适配设计。当前代码已经具备 state、node、route 和 trace 的雏形，迁移难点主要是保持异常语义、重试循环和 `workflow_steps` 输出兼容。

## 2. 当前本地工作流

当前主链路在 `app/services/generator.py` 的 `TestCaseGenerator.generate()` 中。

固定前置节点：

1. `analyze_requirement`
2. `retrieve_knowledge`
3. `route_after_retrieval`
4. `rewrite_query`，仅当 `retrieval_retry_requested=true`
5. `retrieve_rewritten_knowledge`，仅当执行了 rewrite
6. `plan_test_strategy`

LLM 尝试循环：

1. `build_prompt`
2. `check_budget`
3. `call_llm`
4. `validate_output`
5. `post_process_cases`
6. `review_cases`，仅当 `AGENT_REVIEW_ENABLED=true`
7. `route_after_review`，仅当 reviewer 开启
8. `check_quality_gate`，仅当 reviewer 开启且 `AGENT_REVIEW_REQUIRE_PASS=true`
9. `estimate_usage`

循环退出规则：

- `validate_output` 抛 `ValidationError` 时，写入 `state.last_error` 和 `state.correction`，进入下一次 LLM 尝试。
- Reviewer 建议修复且 `AGENT_REVIEW_RETRY_ENABLED=true` 且还有尝试次数时，写入 `state.correction`，进入下一次 LLM 尝试。
- 尝试耗尽后抛 `OutputValidationError`。

阶段评估：正常。节点边界已经清楚，可直接映射为 graph node。

## 3. State 映射

当前 `GenerationWorkflowState` 可以继续作为 LangGraph state 的语义来源。

字段分组：

| 分组 | 字段 |
| --- | --- |
| 输入 | `request` |
| 需求分析 | `analysis` |
| RAG | `contexts`、`knowledge_query`、`rewritten_query`、`retrieval_attempts`、`retrieval_retry_requested` |
| 策略 | `plan` |
| LLM 尝试 | `attempt`、`correction`、`prompt_messages`、`completion_payloads`、`payload`、`last_error` |
| 输出 | `cases`、`usage`、`review`、`retry_requested` |

LangGraph 第一阶段建议使用 `TypedDict` 包装或继续用 dataclass，并让 node 函数返回 state patch。

推荐保守方案：

- 保留 dataclass `GenerationWorkflowState`。
- LangGraph node 内部调用现有 `_xxx_node(state)` 函数。
- node 返回同一个 state 或返回 `{"state": state}`，避免一次性重写所有字段 reducer。

阶段评估：正常。保留 dataclass 能降低迁移风险，但如果后续要使用 checkpoint 和可视化，可能需要再改成可序列化 dict state。

## 4. 节点映射

| 当前节点 | LangGraph 节点 | 备注 |
| --- | --- | --- |
| `_analyze_requirement_node` | `analyze_requirement` | 直接复用 |
| `_retrieve_knowledge_node` | `retrieve_knowledge` | 继续支持延迟 RAG；`knowledge_top_k=0` 不初始化 Chroma |
| `_route_after_retrieval_node` | `route_after_retrieval` | 作为条件边前的决策节点 |
| `_rewrite_query_node` | `rewrite_query` | 只执行一次 |
| `_plan_test_strategy_node` | `plan_test_strategy` | 直接复用 |
| `_build_prompt_node` | `build_prompt` | 每次 LLM 尝试执行 |
| `_check_budget_node` | `check_budget` | 必须在 `call_llm` 前 |
| `_call_llm_node` | `call_llm` | `LLMError` 要保留 usage 注入逻辑 |
| `_validate_output_node` | `validate_output` | `ValidationError` 不应被 LangGraph 包装吞掉 |
| `_post_process_cases_node` | `post_process_cases` | 直接复用 |
| `_review_cases_node` | `review_cases` | 受配置控制 |
| `_route_after_review_node` | `route_after_review` | 决定是否进入下一轮尝试 |
| `_check_quality_gate_node` | `check_quality_gate` | 保留 409 gate 语义 |
| `_estimate_usage_node` | `estimate_usage` | 成功返回前执行 |

阶段评估：正常。节点可以直接复用，第一阶段不需要重写业务函数。

## 5. 条件边设计

### retrieval route

条件函数：

```text
if state.retrieval_retry_requested:
    rewrite_query
else:
    plan_test_strategy
```

`retrieve_rewritten_knowledge` 后必须重置：

```text
state.retrieval_retry_requested = False
```

### review route

条件函数：

```text
if not settings.agent_review_enabled:
    estimate_usage
elif state.retry_requested:
    next_attempt
elif settings.agent_review_require_pass:
    check_quality_gate
else:
    estimate_usage
```

### validation route

当前 `ValidationError` 是 Python `try/except` 控制流。迁移时建议先保留 wrapper：

```text
validate_output_or_retry:
    try validate_output + post_process + review route
    except ValidationError:
        state.last_error = exc
        state.correction = str(exc)
        next_attempt
```

也可以把 validation error 转成 state 标志，但这会改变当前 `workflow_steps` 中 `validate_output=failed` 的记录方式。第一阶段不建议改。

阶段评估：有风险但可控。最关键的是保留 `validate_output` 失败 step 和 reviewer retry 的执行次数。

## 6. 异常语义必须保持

这些异常不能被 LangGraph 吞掉或替换类型：

- `GenerationBudgetExceededError`
- `GenerationQualityGateError`
- `OutputValidationError`
- `LLMError`
- `MissingApiKeyError`

原因：

- API 会把门控错误映射为 409。
- RQ worker 会用 `_error_from_exception()` 生成 `GenerationJobError`。
- `execute_generation()` 会把失败写入生成历史。
- budget gate smoke 依赖 `error.code=budget_exceeded`。

特殊处理：

- `call_llm` 捕获 `LLMError` 后必须注入 `exc.usage` 再重新抛出。
- `check_budget` 必须在 `call_llm` 前执行，避免超预算时真实调用 LLM。
- `OutputValidationError` 必须在尝试耗尽后才抛出。

阶段评估：这是全链路替换的最大风险点。实现时应先写兼容测试，再切换 backend。

## 7. workflow_steps 兼容

当前响应返回：

```text
metadata.workflow_steps: list[WorkflowStep]
```

每个 step 包含：

- `name`
- `status`
- `summary`
- `duration_ms`
- `backend`
- `trace`

当前继续使用 `WorkflowRecorder` 生成兼容结构，而不是直接暴露 LangGraph 原生 event。`backend` 用于标识 `langgraph` 或 `local`，`trace` 用于承载机器可读的节点细节，例如路由决策、召回数、预算估算、Reviewer 分数和 usage。

推荐做法：

- LangGraph node wrapper 内部调用 `workflow.run_node(...)`。
- 或者让 graph 执行完后把 LangGraph event 转换成 `WorkflowStep`。

更稳的选择是第一种，因为现有 summary 函数可以不变。

阶段评估：正常。保持 `WorkflowRecorder` 能让测试和外部响应稳定，同时比纯文本 summary 更利于排障和 GitHub 展示。

## 8. 配置建议

新增配置：

```text
AGENT_WORKFLOW_BACKEND=langgraph
```

允许值：

- `langgraph`：LangGraph 编排 backend，默认值。
- `local`：项目内置 Python 状态机，作为 fallback 和行为对照。

生产启动校验建议：

- production 允许使用 `langgraph` 或 `local`，但推荐保持默认 `langgraph`。
- 回滚时可通过环境变量切到 `local`，不改变 API 契约和历史表结构。

依赖入口：

```text
requirements.txt
requirements-smoke.txt
requirements-langgraph.txt
```

基础依赖和轻量 smoke 依赖均包含 LangGraph；`requirements-langgraph.txt` 保留为兼容入口。

阶段评估：正常。配置开关能降低回归风险。

## 9. 分阶段路线

### Phase 1：文档和测试基线

- 新增本迁移计划。
- 固定现有 generator 行为测试作为兼容基线。
- 明确 TestClient 当前环境会卡住，API 回归用真实 uvicorn/curl 或 Compose smoke。

阶段状态：已完成。已用现有 generator 行为测试固定兼容基线。

### Phase 2：抽象 workflow backend

- 新增 `AgentWorkflowBackend` 或 `GenerationWorkflowRunner` protocol。
- 把当前 `TestCaseGenerator.generate()` 的本地编排提取为 `LocalGenerationWorkflowRunner`。
- `TestCaseGenerator` 根据配置选择 runner。
- 默认切为 `langgraph`，`local` 保留为 fallback。

阶段状态：已完成。现有 `tests/test_generator.py`、配置测试和部署模板测试通过。

### Phase 3：LangGraph backend

- 新增 `LangGraphGenerationWorkflowRunner`。
- 复用现有节点函数。
- 保留 `WorkflowRecorder` 和异常语义。
- 先覆盖成功、RAG rewrite、budget gate、validation retry、review retry、quality gate。

阶段状态：已完成第一轮。`LangGraphGenerationWorkflowRunner` 已复用现有节点函数，成功、RAG rewrite、budget gate、validation retry 等行为测试通过。

阶段门槛：`local` 和 `langgraph` backend 在同一批 generator 行为测试下输出等价。

当前验证：

```bash
./.venv/bin/python -m pytest tests/test_generator.py -q
# 18 passed, 1 skipped
```

阶段评估：正常。LangGraph backend 已能跑通核心生成行为，并已切为默认 backend；基础依赖和轻量 smoke 依赖均已包含框架依赖。

### Phase 4：运行验证

- 本机真实 uvicorn/curl 验证同步生成 budget gate。
- Redis/RQ worker smoke 验证 `budget_exceeded` 仍能落库。
- Docker 轻量 smoke 默认使用 `langgraph`，并继续用预算门控避免真实 LLM 调用。

阶段门槛：API、worker、history、job store 行为不变。

当前状态：`local` backend 的 API/worker smoke 已通过；`langgraph` backend 已完成真实 uvicorn/curl 同步 API smoke 和 Redis/RQ worker smoke，并已切为默认 backend。

当前验证：

```bash
AGENT_WORKFLOW_BACKEND=langgraph ... uvicorn app.main:app --host 127.0.0.1 --port 8017
curl -X POST http://127.0.0.1:8017/api/v1/test-cases/generate ...
# HTTP/1.1 409 Conflict, detail.code=budget_exceeded

AGENT_WORKFLOW_BACKEND=langgraph GENERATION_JOB_QUEUE_BACKEND=rq RQ_QUEUE_NAME=langgraph_smoke ... ./.venv/bin/python scripts/run_generation_worker.py
AGENT_WORKFLOW_BACKEND=langgraph GENERATION_JOB_QUEUE_BACKEND=rq RQ_QUEUE_NAME=langgraph_smoke ... uvicorn app.main:app --host 127.0.0.1 --port 8018
curl -X POST http://127.0.0.1:8018/api/v1/test-cases/generation-jobs ...
# job_id=a5ab704ab02a4af1aa498e6af5d68193
# status=failed, error.code=budget_exceeded, record_id=db9663c4af3e4f09aad8db27c954fc38
# RQ queue length=0

# Default LangGraph sync API smoke, without AGENT_WORKFLOW_BACKEND env var
# api_port=8024
# response=HTTP 409, detail.code=budget_exceeded
# record_id=67adb8dba7a04598a4fe3b6fa75f44b4
# generation_records.status=failed, gate_status=pending

# Default LangGraph Redis/RQ worker smoke, without AGENT_WORKFLOW_BACKEND env var
# api_port=8025
# queue=default-langgraph-smoke
# job_id=c711ebc66f874a5e95cda65655a32b7a
# status=failed, error.code=budget_exceeded
# record_id=712f8ced2f224764927d45aa729311cb
# queue_check: health.ok=true, queued=0, started=0, failed=0, finished=1, worker_count=1
```

阶段评估：正常。LangGraph backend 的同步 API、异步队列、worker 消费、错误映射和历史落库已通过最小 smoke；默认 backend 已从 `local` 切换为 `langgraph`。

### Phase 5：深化集成

- 在默认 LangGraph backend 上评估 checkpoint、interrupt、人审节点和可视化 trace。
- 保留 `local` fallback，作为无框架回滚路径和行为对照。

阶段门槛：核心回归、真实服务 smoke、部署文档和回滚说明均通过。

当前状态：默认值已切换。后续重点不再是“是否使用 LangGraph”，而是是否引入 checkpoint、interrupt 和 trace 到主链路。

## 10. 验收测试

必须覆盖：

```bash
./.venv/bin/python -m pytest tests/test_generator.py tests/test_generation_jobs.py tests/test_history.py -q
```

重点断言：

- 成功生成时 workflow step 名称和顺序兼容。
- RAG 召回不足时只 rewrite 一次。
- `knowledge_top_k=0` 不调用 RAG，不要求 Chroma。
- budget gate 在 LLM 前抛出，`llm.messages == []`。
- validation 失败会进入下一次 attempt，并记录 failed step。
- reviewer retry 会把反馈写入下一轮 Prompt。
- quality gate 失败抛 `GenerationQualityGateError`。
- LLMError 注入 usage 后继续向外抛。
- RQ worker 仍能把门控失败映射成 `GenerationJobError(code="budget_exceeded")`。

## 11. 不建议现在做的事

- 不直接删除本地 workflow。
- 不改 API 响应模型。
- 不把 LangGraph trace 直接暴露给前端替代 `workflow_steps`。
- 不在同一阶段继续叠加 MySQL 默认切换、LangGraph checkpoint 和 Docker 生产镜像大改。
- 不把 human-in-the-loop gate 改成 LangGraph interrupt，第一阶段仍使用现有 gate 持久化。

## 12. 总评估

可行性：高。

推荐方式：先做 backend 抽象，再用 LangGraph 复用现有节点函数。

主要风险：

- 异常类型被包装，导致 API/worker/history 行为变化。
- LLM 尝试循环和 reviewer retry 执行次数变化。
- `workflow_steps` 输出不兼容。
- 新依赖影响 Docker 构建和轻量 smoke。

当前结论：Agent 框架升级已经进入 LangGraph-first 阶段。`langgraph` 后端已通过生成器级、同步 API 和 Redis/RQ worker 最小 smoke，并已成为默认 backend；`local` 后端保留为 fallback。后续重点是 checkpoint、interrupt、人审节点和 trace 深化，而不是继续证明是否能接入 LangGraph。
