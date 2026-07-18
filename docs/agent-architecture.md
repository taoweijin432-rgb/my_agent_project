# Agent 架构

这份文档用于解释本项目从“LLM 调用服务”升级到“可观测 Agent 工作流”的设计，覆盖工作流编排、RAG、记忆、质量门控、成本控制和后续演进方向。

## 1. 当前 Agent 定位

本项目不是聊天型 Agent，而是面向测试用例生成的任务型 Agent。

输入是一段需求、PRD 或功能说明；输出是结构化测试用例。Agent 的职责不是自由对话，而是稳定完成一个工程任务：

```text
需求输入 -> 需求分析 -> 知识检索 -> 召回不足时 query rewrite -> 测试策略规划 -> Prompt 构造 -> 预算门控 -> LLM 生成 -> Schema 校验 -> 后处理 -> Reviewer 审查 -> 质量门控/条件路由 -> 质量评分/历史记录
```

当前核心实现：

- `app/services/generator.py`：生成入口和工作流执行。
- `app/services/agent_workflow.py`：轻量工作流状态、节点抽象、需求分析、测试策略规划。
- `app/services/query_rewrite.py`：召回不足时的本地检索 query 改写。
- `app/services/rag.py`：长期知识库检索。
- `app/services/prompt.py`：Prompt 模板。
- `app/services/reviewer.py`：Reviewer 节点和本地修复反馈。
- `app/services/quality.py`：生成结果质量评分。
- `app/services/history.py`：生成历史和回放。
- `app/services/usage.py`：用量和估算成本统计。

## 2. 为什么先做轻量工作流，而不是直接上 LangGraph

直接引入 LangGraph/LangChain 不是错误，但当前阶段更适合先做轻量编排。

原因：

- 当前任务链路固定，不需要复杂分支图。
- 业务风险在可观测性、校验、历史记录和 RAG 质量，不在框架本身。
- 轻量节点更容易测试，也不会引入额外依赖和学习成本。
- 当节点边界稳定后，可以平滑迁移到 LangGraph。

本项目当前的工作流节点是：

```text
analyze_requirement
retrieve_knowledge
route_after_retrieval
rewrite_query
retrieve_rewritten_knowledge
plan_test_strategy
build_prompt
check_budget
call_llm
validate_output
post_process_cases
review_cases
route_after_review
check_quality_gate
estimate_usage
```

这些节点会写入 `metadata.workflow_steps`，用于排查“是哪一步影响了生成结果”。每个 step 现在包含节点名、状态、摘要、耗时、实际 workflow backend，以及结构化 `trace` 字段。`trace` 用于机器分析路由决策、RAG 召回、预算估算、Reviewer 结论和 usage。

当前已经引入两个接近真实 Agent 框架的核心抽象：

- `GenerationWorkflowState`：一次生成请求里的短期记忆，保存 request、analysis、contexts、plan、attempt、prompt、payload、cases、usage 和 last_error。
- `WorkflowNode`：节点定义，包含节点名、节点动作和节点摘要。
- `WorkflowRecorder.run_node()`：统一执行节点，并把成功、失败、耗时、摘要、backend 和结构化 trace 写入 `workflow_steps`。

这相当于一个最小状态机。节点不再只依赖函数返回值串联，而是读写同一个 state。后续迁移 LangGraph 时，可以把 `WorkflowNode` 映射为 graph node，把 `GenerationWorkflowState` 映射为 graph state。

当前有两类显式条件边。第一类是 RAG 召回修复：

```text
初次 RAG 召回足够 -> plan_test_strategy
初次 RAG 召回不足且启用 query rewrite -> rewrite_query -> retrieve_rewritten_knowledge -> plan_test_strategy
```

第二类是生成结果审查：

```text
Reviewer 通过 -> estimate_usage -> return
Reviewer 不通过且开启自动重试且仍有预算 -> build_prompt -> call_llm
Reviewer 不通过但未开启自动重试或预算耗尽 -> estimate_usage -> return with review
Reviewer 不通过且启用质量门控 -> 409 requires human review
```

默认只记录 Reviewer 结论，不自动重试。原因是重试会增加 LLM 成本，应该由 `AGENT_REVIEW_RETRY_ENABLED` 显式打开。

第三类是成本门控：

```text
Prompt 预算未超限 -> call_llm
Prompt token 或估算费用超限 -> 409 requires human confirmation
```

预算门控发生在 LLM 调用前，目的是在花费真实模型费用之前阻断高成本请求。

## 3. 工作流为什么这样设计

### 3.1 需求分析放在 RAG 前

需求分析是本地确定性逻辑，不调用大模型。它提取：

- 需求长度。
- 用户显式关注的用例类型。
- 安全、性能、兼容性等风险关键词。

这样做的好处：

- 成本为零。
- 可测试、可解释。
- 能提前影响后面的测试策略。

### 3.2 RAG 放在 Prompt 构造前

RAG 的作用是把企业知识放进上下文，减少模型编造。

当前检索结果会进入 Prompt，并且 metadata 会记录：

- `retrieved_chunks`
- `retrieved_sources`
- `source`
- `document_type`
- `module`
- `version`
- `content_hash`
- `updated_at`

RAG 在本项目中不是简单把文档拼接进 Prompt，而是把外部知识作为可追踪、可评估、可版本化的上下文来源。

### 3.3 为什么 query rewrite 放在 RAG 后、Planner 前

初次 RAG 如果没有召回上下文，直接进入 Planner 和 Prompt 会导致模型只能依赖用户输入。query rewrite 节点用本地规则扩展检索词，例如 PRD、接口文档、验收标准、边界值、异常流、权限、安全、性能等。

它放在 RAG 后，是因为只有知道“召回不足”才需要触发；放在 Planner 前，是因为 Planner 应该基于最终可用上下文制定测试策略。

当前 query rewrite 不调用 LLM，原因是：

- 成本为零。
- 行为确定，容易测试。
- 不会把“检索失败”变成另一次模型不确定输出。
- 后续可以升级成 LLM query rewrite 或 hybrid rewrite。

### 3.4 测试策略规划放在 LLM 前

`plan_test_strategy` 是一个“Planner”节点。它会基于需求分析和知识来源决定目标覆盖类型，例如：

- functional
- boundary
- exception
- permission
- security
- performance
- compatibility

Planner 的结果会被注入 Prompt，告诉 LLM 本次生成应该重点覆盖什么。

这样比只写一个大 Prompt 更可控，因为策略是显式节点，可以单测，也可以在历史记录里追踪。

### 3.5 LLM 只负责最适合它的部分

当前设计里，LLM 主要负责生成自然语言测试用例。

不让 LLM 负责：

- 鉴权。
- 数据落库。
- 文件导出。
- 格式最终校验。
- 成本统计。
- 质量评分。

这些都由确定性代码完成。这样系统更稳定，也更容易通过测试证明行为。

### 3.6 Reviewer 为什么用本地规则而不是再调一次大模型

当前 Reviewer 复用 `score_generation_quality()`，检查用例数量、类型覆盖、重复标题、步骤深度、预期结果和知识 grounding。

这样设计的原因：

- 成本可控，默认不会增加额外 LLM 调用。
- 结果稳定，适合作为质量门禁和单元测试对象。
- 反馈可解释，可以直接写入下一轮 Prompt。
- 后续可以升级成“大模型 Reviewer + 本地规则兜底”，但不需要第一步就增加复杂度。

### 3.7 为什么要有预算门控和质量门控

Agent 生产化不能只追求“自动完成”，还要知道什么时候应该停下来。

预算门控由 `check_budget` 节点完成。它在调用 LLM 前估算 prompt token 和费用，如果超过 `AGENT_BUDGET_MAX_PROMPT_TOKENS` 或 `AGENT_BUDGET_MAX_ESTIMATED_COST`，直接返回 409，并把 usage 写入失败历史。

质量门控由 `check_quality_gate` 节点完成。默认不开启；当 `AGENT_REVIEW_REQUIRE_PASS=true` 时，Reviewer 未通过的结果不会直接返回给调用方，而是返回 409，要求人工确认、补充需求或调整知识库。

409 不是普通报错，而是 human-in-the-loop 信号。响应 `detail` 会包含：

- `code`：`budget_exceeded` 或 `quality_gate_failed`。
- `gate`：`budget` 或 `quality`。
- `action_required`：`human_confirmation` 或 `human_review`。
- `usage`：本次估算 token 和费用。
- `review`：质量门控失败时的 Reviewer 结论。

这些门控事件会写入生成历史，并可通过 `GET /api/v1/generation-gates` 单独查询。列表默认只返回 `pending` 记录，也支持 `status=approved`、`status=rejected` 和 `status=all`。处理时调用 `POST /api/v1/generation-gates/{record_id}/resolve`，把记录标记为 `approved` 或 `rejected`；已处理记录不会被重复覆盖。这样前端或外部测试平台可以把它做成待审批列表和审计视图，而不是从普通失败记录里人工筛选。

该设计让 Agent 不只负责调用模型，也具备成本治理和人工介入边界。高成本请求在调用模型前阻断，低质量结果在返回前阻断。

## 4. 记忆架构

Agent 常见记忆可以分为三类：短期记忆、长期记忆、情景记忆。

### 4.1 短期记忆

短期记忆是一次请求中的工作状态。

本项目里包括：

- `GenerateRequest`
- RAG 检索到的 `KnowledgeChunk`
- 初次检索 query 和重写后的 query。
- Planner 输出的测试策略。
- Prompt messages。
- LLM 原始 payload。
- Pydantic 校验错误。
- Reviewer 审查结论。
- workflow trace。
- 预算门控和质量门控状态。

短期记忆由 `GenerationWorkflowState` 显式承载，只在一次生成流程中传递，不直接持久化。持久化的是最终请求、响应、失败原因、usage 和质量评分。

### 4.2 长期记忆

长期记忆是企业知识库。

本项目使用 Chroma 存储：

- PRD。
- API 文档。
- 测试规范。
- 历史业务规则。
- 从其他项目导出的 `knowledge_export/`。

长期记忆通过 embedding 检索进入 Prompt。

### 4.3 情景记忆

情景记忆是 Agent 过去做过什么。

本项目用配置化数据库 backend 保存生成历史，默认是 SQLite，也可切换到已实现并 smoke 通过的 MySQL：

- 请求。
- 响应。
- 失败原因。
- 耗时。
- 质量评分。
- usage 统计。
- request id。

情景记忆的价值是：

- 支持问题回放。
- 支持质量趋势。
- 支持成本统计。
- 支持后续做“参考历史生成”的 few-shot 增强。

## 5. 历史上下文很长时怎么压缩

长上下文处理需要在入口、检索、记忆和 Prompt 多个层面控制。

本项目当前和后续设计可以分为四层。

### 5.1 入口层压缩

不要直接把所有文档塞给模型。当前做法是：

- 文档按 chunk 切分。
- 查询时只取 top_k。
- 默认 `knowledge_top_k <= 10`。

### 5.2 检索层压缩

使用 embedding 检索，把长文档压缩成少量相关片段。

后续可以继续增强：

- metadata filter：按 project、module、document_type 过滤。
- rerank：先召回 top 20，再重排 top 5。
- query rewrite：把需求改写成更适合检索的问题。

### 5.3 记忆层压缩

历史生成记录不能无限塞进 Prompt。正确做法是提炼摘要：

- 保存完整历史到数据库 backend。
- 回放时只取质量高、相似度高的历史记录。
- 对长历史生成“经验摘要”，例如常见边界、常见权限风险。

### 5.4 Prompt 层压缩

Prompt 中只保留对生成有用的信息：

- 当前需求。
- 相关知识片段。
- 测试策略。
- JSON Schema。
- 少量 few-shot。

不放：

- 全量日志。
- 全量历史。
- 不相关文档。
- 大段重复规范。

## 6. 如何降低幻觉

本项目用了多层防护：

- RAG：提供业务事实来源。
- query rewrite：召回不足时自动扩大检索表达。
- Prompt：要求不要编造知识库没有支持的业务规则。
- Schema：强制输出 JSON object。
- Pydantic：后端校验字段和类型。
- Retry：校验失败时把错误反馈给模型重试。
- Reviewer：审查用例覆盖和质量，不通过时可选触发修复重试。
- Gate：预算或质量不满足时停止自动流程，返回人工确认信号。
- post-process：去重、截断、重排 ID。
- quality score：检查类型覆盖、重复、步骤完整度和知识 grounding。

本项目不把“防幻觉”全部押在 Prompt 上，而是用检索、约束、校验、重试和评分组成多层防线。

## 7. Tool Calling 怎么接

当前项目还没有真正使用模型函数调用，但已经具备工具边界。

已有工具能力：

- `RagService.search`
- `RagService.upsert_document`
- `RagService.delete_document`
- `GenerationHistoryStore.list_records`
- `GenerationHistoryStore.get_record`
- `GenerationHistoryStore.list_gate_records`
- `GenerationHistoryStore.resolve_gate_record`
- `InMemoryGenerationJobQueue.submit`
- `InMemoryGenerationJobQueue.get_job`
- `InMemoryGenerationJobQueue.list_jobs`
- `RedisRQGenerationJobQueue.submit`
- `GenerationJobStore.get_job`
- `GenerationJobStore.list_jobs`
- `build_excel`
- `build_pytest_template`
- `score_generation_quality`
- `evaluate_requirement_coverage`

后续如果做 Tool Calling，可以把这些能力封装成工具：

```text
search_knowledge(query, top_k)
list_generation_records(status, limit)
get_generation_record(record_id)
list_generation_gates(status, limit)
resolve_generation_gate(record_id, decision)
submit_generation_job(request)
get_generation_job(job_id)
score_cases(cases)
export_cases(cases)
evaluate_coverage(requirements, cases)
```

注意：不是所有功能都应该开放给 LLM。删除知识库、导出文件、写入历史这类操作需要权限和确认。

## 8. Agent 评估怎么做

Agent 不能只看“能不能生成”，要评估多个层面。

当前已有：

- 单元测试。
- API 测试。
- RAG eval cases。
- 生成质量评分。
- Reviewer 节点和条件重试测试。
- 预算门控和质量门控测试。
- usage 统计。
- 需求覆盖率评估。
- pytest 模板导出测试。

后续建议增加：

- 固定需求回归集。
- 每次 prompt/version 改动后跑生成质量对比。
- 记录 pass rate、平均分、重复率、类型覆盖率。
- RAG source hit rate 和 keyword hit rate。
- 记录需求覆盖率、关键词覆盖率、缺失验收点和人工确认结果。

## 9. Agent 生产化常见问题

### 9.1 如何处理重试

当前只对格式校验失败进行生成重试，重试次数由 `LLM_MAX_RETRIES` 控制。

要注意：

- 重试会增加成本。
- 重试需要记录 attempts。
- 重试后的 prompt 应包含上一次错误。
- 不应该无限重试。

### 9.2 如何处理幂等

生成接口现在不是幂等接口，因为同一个输入可能生成不同输出。

后续可以增加：

- `request_id`
- 输入 hash。
- 缓存相同输入的生成结果。
- 用户确认后再落正式用例库。

### 9.3 如何做安全隔离

当前已经有：

- API key 鉴权。
- CORS 限制。
- 生产启动校验。
- 敏感文件忽略。

后续多人系统需要：

- 用户体系。
- project_id 隔离。
- 多知识库权限。
- 操作审计。

### 9.4 如何控制成本

当前已有：

- attempts。
- duration。
- usage 估算。
- estimated_cost。
- API key 限流。

后续可以增加：

- 每日额度。
- 每用户额度。
- 高成本请求审批。
- 真实 provider usage 采集。

### 9.5 如何选择模型

测试用例生成不是纯聊天任务，更看重：

- JSON 稳定性。
- 中文理解。
- 长上下文能力。
- 成本。
- 响应速度。

可以用小模型做初稿，大模型做评审；也可以用本地规则做预处理和评分，减少大模型调用。

### 9.6 如何提升 QPS 和处理长任务

同步生成接口会让 HTTP 请求一直等待 RAG、LLM、校验、Reviewer 和历史落库完成。这个模式简单，但长需求或批量调用时容易占住连接，用户侧也更容易超时。

当前新增了异步生成队列：

- `POST /api/v1/test-cases/generation-jobs`：提交任务，快速返回 202。
- `GET /api/v1/test-cases/generation-jobs/{job_id}`：查询状态和结果。
- `GET /api/v1/test-cases/generation-jobs`：查看任务列表。

设计边界是：API 层只负责接单，worker 后台复用原有生成链路，因此不会绕过 RAG、Reviewer、门控、usage 和历史记录。当前支持 `GENERATION_JOB_QUEUE_BACKEND=in_memory|rq`。`in_memory` 适合本地开发；`rq` 使用 Redis/RQ 派发任务，并把任务状态写入当前 `DATABASE_BACKEND` 对应的数据库。`GENERATION_JOB_MAX_QUEUE_SIZE` 控制提交背压，队列满时返回 429，避免无限堆积。

这能提升的是“接单 QPS”和长任务承载能力，不代表真实生成吞吐无限提升。真实吞吐仍受模型供应商 QPS/TPM 限流、本机 CPU/内存、Chroma 检索耗时和 worker 数影响。Redis/RQ 解决了 worker 与 API 进程拆分问题；默认 SQLite 状态库仍更适合单机部署，MySQL backend 已实现并通过备份恢复、Compose 模板、完整 Compose smoke、stale 恢复 smoke、5 任务稳定性 smoke、Redis/MySQL 短暂不可用演练、队列告警检查、测试 Agent workflow MySQL/RQ smoke、常驻服务模式 12 job 负载 smoke、2 worker 40 job 负载演练和 Redis/MySQL 依赖抖动恢复演练，但多实例生产还需要补更长时长、更高并发和正式告警阈值校准。

## 10. 工程特性概述

当前实现的主要工程特性：

- 面向测试用例生成的 RAG Agent 服务。
- 生成链路拆分为需求分析、知识检索、测试策略规划、生成、结构化校验、质量评分、历史回放和成本统计。
- 使用 Chroma 管理长期知识，使用配置化数据库 backend 管理情景记忆。
- 使用 Pydantic 做结构化约束，使用 workflow trace 做可观测性。
- 支持 API key、CORS、限流、异步任务队列、启动配置校验、Docker Compose 和敏感数据隔离。

节点化设计的主要原因：

一个 Prompt 难以测试和排查。节点化之后，每一步都能记录输入输出摘要、耗时、失败原因，也能单独演进。例如 RAG 召回差和 LLM 输出格式错是不同问题，应该在不同节点定位。

记忆设计：

短期记忆是一次请求里的 workflow state；长期记忆是 Chroma 知识库；情景记忆是数据库 backend 中的生成历史。默认 SQLite 便于本机开发，MySQL backend 用于多实例共享状态。三者分开后，既能控制上下文长度，也能支持回放、评估和持续优化。

长上下文处理：

系统不会把全量历史塞进模型，而是用 chunk、embedding 检索、top_k、metadata filter、后续 rerank 和历史摘要来压缩。进入 Prompt 的只保留当前任务最相关的信息。

## 11. 后续可升级为真正框架的路线

第一阶段，当前已经完成：

- 显式工作流节点。
- `GenerationWorkflowState` 状态对象。
- `WorkflowNode` 节点抽象。
- Reviewer 节点。
- 条件边 `route_after_review`。
- 条件边 `route_after_retrieval`。
- 本地 query rewrite。
- 预算门控 `check_budget`。
- 质量门控 `check_quality_gate`。
- workflow trace。
- RAG 长期记忆。
- 数据库 backend 情景记忆，默认 SQLite，可选 MySQL。
- 质量评分。
- usage 统计。

第二阶段，可以引入 LangGraph：

- 把节点改成 graph node。
- 将 `GenerationWorkflowState` 映射为 graph state。
- 增加更多条件边：检索长期不足 -> 知识库维护任务；多次质量门控失败 -> 人工审核队列；预算门控失败 -> 审批工作流。

第三阶段，做多 Agent：

- Planner Agent：拆解测试策略。
- Generator Agent：生成用例。
- Reviewer Agent：审查覆盖和质量。
- Exporter Tool：导出和平台适配。

不要为了框架而框架。真正有价值的是：状态清晰、节点可测、失败可恢复、成本可控、结果可评估。

发布后的升级应以 [architecture-baseline.md](architecture-baseline.md) 作为对照基线，以 [release-checklist.md](release-checklist.md) 作为交付检查清单。后续引入 Redis 队列、MySQL 或 LangGraph 时，应优先保持现有 API 语义、状态字段和 workflow trace 可观测输出稳定。
