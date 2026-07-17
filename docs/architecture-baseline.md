# 架构基线

本文固定当前发布架构，作为后续升级 MySQL 生产化、LangGraph 默认链路和可观测性的对照基线。

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
Database Backend + Chroma Knowledge Base
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
- `app/services/coverage.py`：需求验收点到测试用例的覆盖率评估。
- `app/services/pytest_exporter.py`：pytest 自动化模板导出。
- `app/services/usage.py`：token 和费用估算。
- `app/services/history.py`：SQLite 生成历史和门控处理实现。
- `app/services/generation_job_store.py`：SQLite 异步任务状态实现。
- `app/services/mysql_stores.py`：MySQL 生成历史、门控处理和异步任务状态实现。
- `app/services/stores.py`：数据库 backend factory，按 `DATABASE_BACKEND=sqlite|mysql` 选择实现。
- `app/services/generation_jobs.py`：进程内队列和 Redis/RQ 队列 adapter。
- `app/workers/generation_rq.py`：Redis/RQ worker 任务入口。

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
-> GenerationJobQueue.submit()
-> in-memory queue or Redis/RQ
-> worker calls original generation chain
-> job status becomes succeeded/failed in memory or configured database backend
-> GET /test-cases/generation-jobs/{job_id}
```

门控处理：

```text
Budget/quality gate failed
-> GenerationGateError
-> HTTP 409 or async job failed
-> gate detail persisted in configured database backend
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

- 配置化数据库 backend 中的生成历史。
- 默认 `DATABASE_BACKEND=sqlite`，也可切换到已实现并 smoke 通过的 `DATABASE_BACKEND=mysql`。
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
- 需求覆盖率评估和缺口反馈。
- Excel 与 pytest 模板导出。
- 内部运行指标 JSON 和 Prometheus 文本输出，覆盖 readiness、job 状态计数、生成历史成功/失败、generation gate 状态、历史 token/cost 聚合、队列 registry/worker、HTTP 请求量/状态码/耗时桶，以及 LLM 配置、call/attempt/retry/错误码/耗时桶指标。
- 进程内异步任务队列、Redis/RQ 外部队列和队列满背压。
- 数据库 backend 抽象，默认 SQLite，MySQL backend 已完成本机 Docker smoke。

仍需外部基础设施补齐：

- HTTPS 网关。
- 网关层限流。
- 集中日志。
- metrics 采集系统和告警规则落地。
- MySQL 生产部署硬化、备份恢复和默认 backend 切换。
- 队列可观测性和严格原子背压。
- 密钥管理。

## 7. 升级边界

外部队列现状：

- 保留 API 模型：`GenerationJobDetail`、`GenerationJobSummary`、`GenerationJobError`。
- 保留 API 路径：`/test-cases/generation-jobs`。
- 已新增 Redis/RQ adapter，并把任务状态写入配置化数据库 backend。
- 默认 SQLite 适合单机部署；MySQL backend 已实现并通过 Redis/RQ worker smoke、备份恢复、Compose 模板、stale 恢复 smoke、5 任务稳定性 smoke、Redis/MySQL 短暂不可用演练脚本、RQ worker stability smoke、queue alert 阈值检查和测试计划执行 job MySQL 持久化验证；生产默认切换仍需补更长时长运行验证。

MySQL 现状：

- 已保留 `GenerationHistoryStore` 对外方法语义，并新增 repository protocol/factory。
- 已将 SQLite 运行表结构映射为 `migrations/mysql/001_initial.sql`。
- 已把生成历史、门控处理、异步任务状态纳入 MySQL backend。
- 当前默认仍是 `DATABASE_BACKEND=sqlite`；Compose MySQL 模板、备份恢复文档、端到端 smoke、stale 恢复 smoke、备份恢复演练、5 任务稳定性 smoke、Redis/MySQL 短暂不可用演练脚本、RQ worker stability smoke、queue alert 阈值检查和测试计划执行 job MySQL 持久化验证已完成。生产切换前仍需要补更长时长运行验证。

LangGraph 升级：

- 默认 backend 已切为 `AGENT_WORKFLOW_BACKEND=langgraph`，`local` backend 保留为 fallback 和行为对照。
- `GenerationWorkflowState` 映射为 graph state。
- 当前节点函数映射为 graph node。
- 现有 route 节点映射为 conditional edge。
- `workflow_steps` 继续作为对外可观测输出。
- 第一阶段不替换异常语义、Prompt、RAG、Reviewer、门控和历史落库。

RAG 升级：

- 保留 `RagService.search()` 作为业务入口。
- 增加 metadata filter、rerank、召回评估指标。
- 避免把调用方直接绑定到具体向量库实现。

测试质量升级：

- 保留 `evaluate_requirement_coverage()` 作为确定性覆盖率评估入口。
- 当前覆盖率评估基于关键词映射，适合作为缺口初筛，不替代人工验收。
- 后续可以增加同义词、权重、语义相似度和人工确认回流。
- pytest 导出当前是模板能力，后续可按业务接口增加可执行 adapter。

## 8. 发布判断

当前架构满足发布基线：

- 主链路完整。
- 关键失败路径可解释。
- 人工介入有闭环。
- 长任务有异步入口。
- 文档和测试可以支撑交付。

当前架构不应宣称为完整生产最终态：

- 默认 SQLite 仍不是多实例基础设施；MySQL backend 可用但尚未作为生产默认。
- 权限和监控还不完整。
- RAG 评估和线上质量治理还需要继续增强。
