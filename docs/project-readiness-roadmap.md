# 项目现状评估与后续路线

最后更新：2026-06-25

## 1. 总体结论

当前项目已经达到“可本机运行、可演示、可被外部系统初步集成”的后端基线。核心生成链路、默认 LangGraph 工作流、RAG、历史记录、门控、异步任务、Redis/RQ worker 和 MySQL backend 都已有实现和阶段性 smoke 验证。登录模块已补充结构化知识库并完成多轮真实 RAG 生成验证，验证结论是：补知识库能显著改善覆盖，但仍需要覆盖修复或强质量门控兜底模型随机遗漏。

当前不应宣称为完整公网多租户生产系统。主要差距不在主业务链路，而在生产数据库默认切换、Docker 生产模板、备份恢复、队列可观测性、权限隔离、集中监控、真实 RAG 质量治理和长期稳定性验证。

阶段评估：正常。项目主干能力完整，后续应按生产化优先级推进，不建议继续无边界地增加新功能。

## 2. 当前可用能力

已经具备：

- FastAPI REST API：同步生成、异步生成、Excel 导出、知识库导入和查询。
- RAG 知识库：Chroma 存储，支持导入、查询、upsert、delete；已新增登录模块结构化验收矩阵 `knowledge/prd/login/default-langgraph-full-chain.md`。
- Agent 工作流：需求分析、检索、query rewrite、测试策略规划、Prompt 构建、LLM 调用、结构化校验、Reviewer、质量门控和成本估算。
- 生成历史与门控审计：生成记录、失败原因、usage、质量报告、预算/质量门控详情和审批闭环。
- 异步任务：进程内队列和 Redis/RQ 外部队列，独立 worker，任务状态持久化。
- 数据库 backend：默认 SQLite，可选 MySQL；MySQL 已通过 store smoke 和 Redis/RQ worker smoke。
- Agent 框架演进：默认 LangGraph backend，local backend 保留为 fallback；已完成生成器级、同步 API 和 Redis/RQ worker smoke。
- 工程基线：API key、CORS、应用内限流、请求 ID、启动配置校验、Dockerfile、Compose 模板、轻量 smoke compose 和技术文档。

当前验证基线：

```bash
./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_ingest_documents.py tests/test_startup_validation.py tests/test_config.py tests/test_quality.py tests/test_usage.py tests/test_reviewer.py tests/test_rag_evaluation.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_models.py tests/test_query_rewrite.py tests/test_rag.py tests/test_stores.py tests/test_mysql_migration.py -q
# 89 passed, 1 skipped, 2 warnings
```

## 3. 项目目标定义

建议把目标拆成三个层级，避免把“可用”“准生产”和“完整生产”混在一起。

### 3.1 当前目标：可演示、可集成

目标状态：

- 本机或单机 Docker 环境可以稳定启动。
- API 文档清楚，外部调用方能完成生成、查询、导出、知识库维护和门控审批。
- 异步长任务不会阻塞 HTTP 连接。
- 失败路径可解释，生成历史可回放。

当前评估：基本达成。还需要补一轮端到端运行手册演练和发布前清理。

### 3.2 下一目标：单机准生产

目标状态：

- Redis/RQ 为默认异步队列。
- MySQL 可作为运行数据库，并有 Compose 服务模板、初始化、备份、恢复和回滚说明。
- Docker 镜像能在网络稳定环境完成完整依赖构建。
- 运行数据、模型缓存、Chroma 数据、日志和密钥都有明确持久化策略。
- 最小监控指标能覆盖 API 健康、队列长度、失败率和成本。

当前评估：部分达成。Redis/RQ 和 MySQL backend 已可用，MySQL Compose 模板、运维文档、本机 API/worker 端到端 smoke、恢复演练、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke 已完成；仍缺少更长时长运行、worker crash、Redis/MySQL 短暂不可用等故障恢复验证。

### 3.3 长期目标：多实例生产

目标状态：

- API、worker、Redis、MySQL 和 Chroma 数据持久化边界清楚。
- 限流、鉴权、日志、metrics、告警、备份恢复和密钥管理由外部基础设施承接。
- 队列背压具备更严格的原子语义。
- 支持用户、项目、知识库权限隔离。
- RAG 质量有固定评估集、召回指标、rerank 和线上反馈闭环。

当前评估：尚未达成。这一阶段需要产品化和运维投入，不只是代码补丁。

## 4. 关键差距

| 领域 | 当前状态 | 主要缺口 | 优先级 |
| --- | --- | --- | --- |
| 数据库 | SQLite 默认，MySQL backend 已可用 | MySQL Compose 服务、备份恢复、连接池参数、默认切换策略 | P0 |
| 队列 | Redis/RQ 已可用，5 任务稳定性 smoke 已通过，已新增队列检查脚本 | 原子背压、worker crash 恢复、Redis/MySQL 短暂不可用验证 | P0 |
| Docker | 轻量 smoke 已通过 | 完整 ML/RAG 依赖构建、镜像体积、缓存策略、bind mount 权限说明 | P0 |
| 运行验证 | 单点 smoke、完整 Compose smoke 和 5 任务稳定性 smoke 已通过 | 持续运行、worker crash、MySQL/Redis 断连恢复 | P0 |
| RAG 质量 | 有导入、查询和基础评估脚本 | 固定评估集、metadata filter、rerank、业务知识整理规范 | P1 |
| Agent 框架 | LangGraph 可选 backend 已通过 smoke | 是否切默认、依赖体积、回滚策略、checkpoint/interrupt 深度集成 | P1 |
| 可观测性 | 请求 ID 和耗时响应头 | 结构化日志、metrics、成本统计面板、告警 | P1 |
| 安全权限 | API key 和 CORS | 用户体系、项目隔离、RBAC、知识库授权、审计 | P2 |
| 平台集成 | REST API 和 Excel 导出 | 禅道/TestRail/飞书等 adapter、字段映射、回写状态 | P2 |

阶段评估：正常。最高优先级应集中在数据库、队列、Docker 和运行验证，这些直接决定项目是否能从“能跑”进入“可长期运行”。

## 5. 后续工作路线

### Phase 1：MySQL 生产化

目标：让 MySQL 成为可选择的准生产运行数据库，而不是只停留在代码路径和 smoke。

工作项：

- 在 `docker-compose.yml` 或独立 override 文件中增加 MySQL 服务模板。已完成：`docker-compose.mysql.yml`。
- 增加 MySQL volume、健康检查、初始化流程和环境变量示例。已完成。
- 明确本机 Python、Compose API、Compose worker 三种连接地址。已完成。
- 增加备份和恢复说明，包括 `mysqldump`、volume 保留和恢复演练。已完成并通过一次恢复演练。
- 梳理 `DATABASE_BACKEND=mysql` 的启动校验和常见错误说明。
- 做 API + worker + Redis + MySQL 的端到端 smoke 脚本或手册。已完成本机 Python API/worker + Docker Redis + Compose MySQL smoke、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke。

验收标准：

- 一条文档化命令能启动 Redis、MySQL、API 和 worker。
- 初始化 schema 后异步任务能写入 MySQL 的 `generation_jobs` 和 `generation_records`。已通过。
- 停止并重启 API/worker 后，历史记录和任务记录仍可查询。MySQL 重启持久化、完整 Compose API/worker 重启检查和稳定性 smoke 重启读取均已通过。
- 备份文件能恢复到新的 MySQL volume。已通过，恢复目标 `agent_restore_test_mysql-data`。

建议状态：Phase 1 基本完成。MySQL backend、Compose override、备份恢复和稳定性 smoke 已完成，默认仍保持 SQLite。

### Phase 2：Docker 与运行环境硬化

目标：让项目在 Linux/Docker 环境中稳定构建、启动和验证。

工作项：

- 验证完整 `requirements.txt` 或 `requirements-ml.txt` 镜像构建。已完成：`requirements.txt` 基础完整镜像构建通过；切到默认 LangGraph 前 `ai-testcase-generator:local` 约 `762MB`、轻量 smoke 镜像约 `270MB`，加入 LangGraph 依赖后需重建确认新体积；`INSTALL_ML_DEPS=true IMAGE_TAG=ml` CPU-only 语义 embedding 镜像构建通过，`ai-testcase-generator:ml` 约 `2.33GB`。
- 记录网络不稳定时的依赖缓存策略和镜像源配置。
- 明确 `requirements-smoke.txt`、`requirements-mysql.txt`、`requirements-langgraph.txt`、`requirements-ml.txt` 的使用边界。
- 补 bind mount 权限检查脚本或排障步骤。已完成：新增 `scripts/check_runtime_paths.py`，API/worker 容器启动前会检查 Chroma、模型缓存和 SQLite 目录可写性。
- 增加容器启动后的健康检查、日志查看和数据目录检查命令。

验收标准：

- 轻量 smoke 和完整镜像构建路径都能说明清楚。
- 新环境按文档能完成依赖安装、容器启动和 smoke。
- SQLite、Chroma、模型缓存、MySQL、Redis 的数据持久化边界清楚。

### Phase 3：队列稳定性与可观测性

目标：让 Redis/RQ 不只是能消费任务，还能被运维和排障。

工作项：

- 增加队列长度、失败任务数、运行中任务数和 worker 心跳状态查询。已完成：`scripts/check_generation_queue.py` 输出 RQ queued/started/finished/failed/deferred/scheduled、worker 心跳和数据库任务状态统计。
- 对 RQ failed registry 与业务表 `generation_jobs` 做对账策略。已完成第一版：脚本会比较数据库 active jobs 与 RQ active registry，并支持 `--fail-on-mismatch`。
- 评估原子背压方案：MySQL 事务、Redis Lua 或单独计数器。
- 补 worker crash、Redis 短暂不可用、任务 stale recovery 的手工验证记录。
- 增加结构化日志字段：request_id、job_id、record_id、workflow_backend、database_backend、duration_ms、error_code。

验收标准：

- 队列异常能被定位到 Redis、worker、业务表或生成链路。
- worker 重启后 stale running 任务能被标记失败。
- 队列满、Redis 不可用和业务门控失败都有明确 API 响应。

### Phase 4：RAG 质量提升

目标：让生成质量更多依赖可评估的知识库，而不是只依赖 Prompt 和模型随机性。

工作项：

- 已完成第一步兜底：Reviewer/Quality 会把已召回 RAG 片段中的关键验收点纳入覆盖检查，并把缺失项结构化返回为 `missing_acceptance_keywords`。
- 已补登录模块结构化知识库，真实 v4-v7 验证确认 RAG 可召回矩阵项，但模型仍可能遗漏个别验收点。
- 已增加覆盖修复反馈：Reviewer 会把缺失类型和缺失验收点写入 `GenerationReview`，重试 Prompt 会要求补齐缺口并在满额时替换低价值用例；开启强质量门控后，重试仍缺失会返回 409。
- 已建立登录模块固定 RAG 评估集，隔离 collection 验证 `source_hit_rate=1.0`、`keyword_hit_rate=1.0`、`case_pass_rate=1.0`。
- 已完成真实链路强门控 smoke：不达标请求返回 `quality_gate_failed` 409，足量请求经 `coverage_repair` 后返回 200 且 Reviewer 通过。
- 继续建立更多固定 RAG 评估集，覆盖权限、异常、边界、性能、安全等业务类型。
- 增加 metadata filter，按 project、module、document_type 过滤。
- 评估 rerank 方案，先召回 top 20，再重排 top 5。
- 制定知识库整理规范：文档来源、chunk 规则、版本、模块、过期文档处理。
- 把生成历史中的人工反馈沉淀为后续评估或 few-shot 候选数据。

验收标准：

- 每次知识库变更后能跑固定评估集。
- 召回结果能解释命中的 source、module、document_type 和 chunk。
- 典型业务需求的 top_k 命中质量有可比较指标。

### Phase 5：LangGraph 深化集成

目标：在默认 LangGraph backend 基础上，评估 checkpoint、interrupt 和可视化 trace 是否进入主链路。

工作项：

- 持续对比 `local` 和 `langgraph` 的行为一致性、耗时和依赖体积。
- 补同步 API、Redis/RQ worker、门控失败、Reviewer retry、validation retry 的对照验证。
- 明确回滚策略：环境变量切回 `local`，不改 API 契约和历史表。
- 评估 checkpoint、interrupt、人审节点和可视化 trace 是否进入下一阶段。

验收标准：

- 切换 backend 不改变 API 响应结构、错误码、历史记录和任务状态。
- Docker 完整镜像能安装 LangGraph 可选依赖。
- 有明确默认切换和回滚文档。

### Phase 6：产品化与集成

目标：从技术后端走向可被团队使用的工具。

工作项：

- 增加用户、项目、知识库权限模型。
- 增加测试平台 adapter，例如禅道、TestRail、飞书多维表格。
- 增加生成模板和策略配置。
- 增加人工评审结果回流，形成质量闭环。
- 增加前端或管理后台，用于知识库、历史记录、门控审批和任务监控。

验收标准：

- 不同项目的数据和知识库可以隔离。
- 生成结果能按目标平台字段导出或回写。
- 人工审核结果能影响后续质量评估。

## 6. 建议执行顺序

推荐顺序：

1. worker crash、Redis 短暂不可用和 MySQL 短暂不可用恢复验证。
2. 原子背压方案评估与实现。
3. 结构化日志和失败对账增强。
4. RAG 固定评估集、metadata filter 和 rerank。
5. LangGraph 默认切换评估。
6. 用户权限、平台 adapter 和前端管理面。

不建议现在优先做：

- 继续用自研 local backend 作为项目主体。
- 直接做多用户前端管理后台。
- 直接替换向量数据库。
- 直接上 Celery 重写队列。
- 在没有评估集的情况下反复调 Prompt。

阶段评估：正常。当前最有性价比的是把运行基础设施补稳，而不是继续扩展业务功能面。

## 7. 下一步最小任务包

建议下一步只做一个最小闭环：

目标：完成队列故障恢复验证和背压方案评估。

已完成：

- 新增 Compose MySQL 服务或 override 文件。
- 更新 `.env.runtime.example` 中的 MySQL 配置示例。
- 增加 MySQL 初始化、备份、恢复文档。
- 跑一次 Redis/RQ + MySQL + API + worker smoke。
- 完成 MySQL 备份恢复演练。
- 完成完整 Compose API/worker 镜像 smoke。
- 完成 Redis/RQ + MySQL + API + worker 5 任务稳定性 smoke：5 条任务均入队、执行、写入 MySQL 并以 `budget_exceeded` 失败；MySQL `generation_jobs=5`、`generation_records=5`；RQ `queue_count=0`、`finished_count=5`；API/worker 重启后可读取历史 job。
- 修正 `worker` Compose 服务继承 Dockerfile HTTP healthcheck 导致误判 unhealthy 的问题：worker 服务显式 `healthcheck.disable=true`。
- 新增 `scripts/check_runtime_paths.py`，并接入 Dockerfile API 默认启动命令和 Compose worker 命令；容器启动前会检查 `CHROMA_PATH`、`EMBEDDING_CACHE_DIR` 和 SQLite 历史库目录是否可写。
- 完成一次轻量 Compose runtime path smoke：`agent_runtime_path_smoke` project 中 API healthy、worker up，二者日志均输出 `Runtime path check passed.`。
- 完成 `requirements.txt` 基础完整镜像构建：`COMPOSE_PROJECT_NAME=agent_full_requirements_build REQUIREMENTS_FILE=requirements.txt INSTALL_ML_DEPS=false docker compose -f docker-compose.yml build api`，切到默认 LangGraph 前镜像 `ai-testcase-generator:local` 约 `762MB`；加入 LangGraph 依赖后需重建确认新体积。
- 完成 ML 镜像构建：`COMPOSE_PROJECT_NAME=agent_ml_build IMAGE_TAG=ml REQUIREMENTS_FILE=requirements.txt INSTALL_ML_DEPS=true docker compose -f docker-compose.yml build api`，镜像 `ai-testcase-generator:ml` 约 `2.33GB`，容器内验证 `torch=2.12.1+cpu`、`cuda_available=False`、`sentence_transformers=5.6.0`。
- 将 Compose 镜像 tag 改为 `IMAGE_TAG` 可配置，默认基础镜像 `local`、smoke override 默认 `smoke`、ML 构建使用 `ml`，避免不同依赖层互相覆盖。
- 将 `requirements-ml.txt` 固定到 PyTorch CPU wheel：`torch==2.12.1+cpu`，避免默认 PyPI 拉取 CUDA/NVIDIA 依赖。
- 新增 `scripts/check_generation_queue.py`，输出 RQ registry、worker 心跳和数据库任务状态统计，并支持 `--json`、`--fail-on-mismatch`。
- 将 Agent 默认 backend 切为 `langgraph`，基础依赖和轻量 smoke 依赖均包含 LangGraph，`local` backend 保留为 fallback。
- 更新 `docs/codex-handoff.md` 和 `docs/issues.md` 验证记录。

下一步范围：

- 补 worker crash、Redis 短暂不可用、MySQL 短暂不可用和 stale recovery 手工验证记录。
- 评估原子背压方案：MySQL 事务、Redis Lua 或单独计数器。
- 增加结构化日志字段，便于从 API、worker、数据库和队列之间串联一次生成请求。

完成后再进入 RAG 固定评估集、metadata filter 和 rerank。

## 8. 当前风险清单

- 默认 SQLite 仍不适合多实例共享状态。
- MySQL backend 已可用，生产化模板、备份恢复文档、恢复演练、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke 已完成；默认仍未切到 MySQL。
- Redis/RQ 背压不是严格原子有界队列；已新增 `scripts/check_generation_queue.py` 做基本队列/业务表对账，但还缺 worker crash 与短暂断连恢复验证。
- `requirements.txt` 基础完整镜像和 `INSTALL_ML_DEPS=true` CPU-only 语义 embedding 镜像已通过；后续重新构建仍受网络和 `torch/scipy` 等重依赖下载影响。
- LangGraph 已是默认 backend，local backend 仅作为 fallback；`workflow_steps` 已补结构化 trace，checkpoint、interrupt、人审节点和外部 trace viewer 尚未深度集成。
- 当前环境 FastAPI `TestClient` 会卡住，API 级验证应继续使用真实 uvicorn/curl 或 Compose smoke。
- 缺少集中日志、metrics、告警和真实网关层限流。
- 缺少用户、项目、知识库权限隔离。

总评估：项目已经具备阶段性交付价值。后续目标不是推倒重写，而是按 Docker、队列、RAG、框架、产品化的顺序，把当前可用基线推进到可长期运行的工程形态。
