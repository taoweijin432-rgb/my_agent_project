# 架构基线

本文固定当前封版架构，作为后续升级 Redis 队列、PostgreSQL、LangGraph 和可观测性的对照基线。

## 1. 当前定位

当前项目是一个面向测试用例生成的 RAG Agent 后端服务。它不是聊天机器人，也不是完整测试管理平台。

核心职责：

- 接收自然语言需求、PRD 摘要或功能说明。
- 从知识库检索相关业务规则。
- 调用 LLM 生成结构化测试用例。
- 用确定性代码做格式校验、质量审查、成本估算、门控和历史记录。
- 通过 REST API 被外部系统或前端集成。

## 2. 架构分层

```text
Client / Test Platform
        |
FastAPI API Layer
        |
Generation Orchestration
        |
Agent Workflow State + Nodes
        |
RAG / Prompt / LLM / Reviewer / Gates
        |
SQLite History + Chroma Knowledge Base
```

主要模块：

- `app/api/routes.py`：HTTP API、鉴权依赖、同步/异步生成入口。
- `app/services/generator.py`：生成链路编排。
- `app/services/agent_workflow.py`：状态对象、节点抽象和 workflow trace。
- `app/services/rag.py`：Chroma 知识库和 embedding 封装。
- `app/services/query_rewrite.py`：召回不足时的本地 query rewrite。
- `app/services/prompt.py`：Prompt 模板。
- `app/services/reviewer.py`：Reviewer 节点和修复反馈。
- `app/services/quality.py`：本地质量评分。
- `app/services/usage.py`：token 和费用估算。
- `app/services/history.py`：SQLite 生成历史和门控处理。
- `app/services/generation_jobs.py`：进程内异步任务队列。

## 3. 关键数据流

同步生成：

```text
POST /test-cases/generate
-> GenerateRequest
-> TestCaseGenerator.generate()
-> workflow nodes
-> GenerateResponse
-> GenerationHistoryStore.record_success/record_failure
-> HTTP response
```

异步生成：

```text
POST /test-cases/generation-jobs
-> InMemoryGenerationJobQueue.submit()
-> queued job
-> worker calls original generation chain
-> job status becomes succeeded/failed
-> GET /test-cases/generation-jobs/{job_id}
```

门控处理：

```text
Budget/quality gate failed
-> GenerationGateError
-> HTTP 409 or async job failed
-> gate detail persisted in SQLite
-> GET /generation-gates
-> POST /generation-gates/{record_id}/resolve
```

## 4. Agent 记忆基线

短期记忆：

- `GenerationWorkflowState`
- 只在一次生成流程中存在。
- 保存 request、analysis、contexts、plan、prompt、payload、cases、review、usage 和 last_error。

长期记忆：

- Chroma 知识库。
- 保存 PRD、接口说明、测试规范、历史用例、业务规则等 chunk。

情景记忆：

- SQLite 生成历史。
- 保存请求、响应、失败原因、usage、质量报告、门控 detail 和门控处理状态。

## 5. 工作流基线

当前节点顺序：

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

已存在的条件边：

- RAG 召回不足 -> query rewrite -> 再检索。
- Reviewer 未通过且允许重试 -> 带反馈重试。
- Prompt 成本超限 -> 预算门控 409。
- Reviewer 未通过且强质量门控开启 -> 质量门控 409。

## 6. 当前生产化能力

已具备：

- API key 鉴权。
- CORS 配置。
- 应用内限流。
- 请求 ID 和耗时响应头。
- 生产启动配置校验。
- Dockerfile 和 Docker Compose 模板。
- 运行数据、密钥、模型缓存、向量库和私有知识库忽略规则。
- 生成历史和门控审计。
- 异步任务队列和队列满背压。

仍需外部基础设施补齐：

- HTTPS 网关。
- 网关层限流。
- 集中日志。
- metrics 和告警。
- 外部队列。
- 生产数据库。
- 密钥管理。

## 7. 升级边界

外部队列升级：

- 保留 API 模型：`GenerationJobDetail`、`GenerationJobSummary`、`GenerationJobError`。
- 保留 API 路径：`/test-cases/generation-jobs`。
- 替换实现：`InMemoryGenerationJobQueue` -> Redis/RQ/Celery adapter。
- 任务状态需要持久化到数据库，避免进程重启后丢失。

PostgreSQL 升级：

- 保留 `GenerationHistoryStore` 对外方法语义。
- 将 SQLite 表结构映射为 PostgreSQL migration。
- 把生成历史、门控处理、异步任务状态统一纳入事务边界。

LangGraph 升级：

- `GenerationWorkflowState` 映射为 graph state。
- 当前节点函数映射为 graph node。
- 现有 route 节点映射为 conditional edge。
- `workflow_steps` 继续作为对外可观测输出。

RAG 升级：

- 保留 `RagService.search()` 作为业务入口。
- 增加 metadata filter、rerank、召回评估指标。
- 避免把调用方直接绑定到具体向量库实现。

## 8. 封版判断

当前架构满足基线封版：

- 主链路完整。
- 关键失败路径可解释。
- 人工介入有闭环。
- 长任务有异步入口。
- 文档和测试可以支撑交付。

当前架构不应宣称为完整生产最终态：

- 队列和数据库还不是多实例基础设施。
- 权限和监控还不完整。
- RAG 评估和线上质量治理还需要继续增强。
