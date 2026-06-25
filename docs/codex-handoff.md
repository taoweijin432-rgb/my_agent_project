# Codex 项目交接摘要

项目：AI 测试用例生成助手

当前阶段：Redis/RQ 外部队列已接入，Docker 轻量 smoke 已通过，MySQL backend 已实现并通过 store smoke、备份恢复、完整 Compose smoke 和多任务稳定性 smoke；Docker 启动前运行目录权限检查已接入 API/worker；LangGraph 已是默认 backend；RAG 全链路真实生成已跑通，并已补强 Prompt/Reviewer/Quality 对知识库验收点的覆盖约束。

目标下一步：将登录 RAG 固定评估和强质量门控 smoke 接入本地发布检查或 CI；随后继续队列故障恢复验证。

## 当前最新提交

- `48d12fb docs: add release baseline`
- `91f8128 feat: add async generation job queue`
- `ab2d6cd feat: resolve generation gate events`
- `2cccdb8 feat: persist generation gate events`

## 当前能力

项目已经具备：

- FastAPI REST API
- Chroma RAG 知识库
- embedding 配置化
- 显式 Agent workflow
- `GenerationWorkflowState` 短期记忆
- workflow trace
- query rewrite
- Planner 测试策略规划
- Prompt 对 focus_types、知识库数字/时长/次数/状态/权限/安全约束和 Few-shot 污染有明确约束
- Pydantic 输出校验
- Reviewer Agent 本地质量审查，会把用户需求和已召回 RAG 内容中的关键验收点纳入覆盖检查
- 预算门控、质量门控
- human-in-the-loop 门控审批闭环
- SQLite 生成历史
- usage / cost 估算
- 进程内异步生成任务队列
- Redis/RQ 外部任务队列和独立 worker
- API key、CORS、限流、生产启动配置校验
- Dockerfile、docker-compose.yml、轻量 smoke compose 和部署文档
- MySQL 迁移评估和 Phase 1 store 抽象：`docs/mysql-migration-plan.md`
- LangGraph 迁移评估：`docs/langgraph-migration-plan.md`
- 封版文档：`docs/release-checklist.md`
- 架构基线：`docs/architecture-baseline.md`

## 最近验证

第三步验证结果：

```bash
./.venv/bin/python -m pytest tests/test_generator.py -q
# 14 passed

./.venv/bin/python -m pytest tests/test_deployment_templates.py -q
# 4 passed

docker build --check .
# Check complete, no warnings found.

REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml build
# Image ai-testcase-generator:smoke Built
```

Compose smoke 结果：API、worker、Redis 均启动正常；提交异步任务 `0031c4a8a92d4912893bfe2ed8a7556a` 后，worker 消费成功，最终状态为 `failed`，`error.code=budget_exceeded`，SQLite 写入 `generation_jobs` 和 `generation_records`，RQ 队列长度为 `0`。

第四步验证结果：

```bash
./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_ingest_documents.py tests/test_startup_validation.py tests/test_config.py tests/test_quality.py tests/test_usage.py tests/test_reviewer.py tests/test_rag_evaluation.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_models.py tests/test_query_rewrite.py tests/test_rag.py -q
# 77 passed, 3 warnings
```

本轮仍排除了 FastAPI `TestClient` 相关测试文件，因为当前环境已知 `TestClient` 会卡住。

LangGraph backend 验证：

```bash
./.venv/bin/python -m pytest tests/test_generator.py tests/test_config.py tests/test_deployment_templates.py -q
# 37 passed

./.venv/bin/python -m pytest tests/test_generator.py -q
# 18 passed, 1 skipped

./.venv/bin/python -m pytest tests/test_config.py tests/test_deployment_templates.py tests/test_agent_workflow.py tests/test_generation_jobs.py tests/test_history.py -q
# 32 passed

./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_ingest_documents.py tests/test_startup_validation.py tests/test_config.py tests/test_quality.py tests/test_usage.py tests/test_reviewer.py tests/test_rag_evaluation.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_models.py tests/test_query_rewrite.py tests/test_rag.py -q
# 82 passed, 1 skipped, 2 warnings

AGENT_WORKFLOW_BACKEND=langgraph ... uvicorn app.main:app --host 127.0.0.1 --port 8017
curl -X POST http://127.0.0.1:8017/api/v1/test-cases/generate ...
# HTTP 409, detail.code=budget_exceeded, failed history persisted

AGENT_WORKFLOW_BACKEND=langgraph GENERATION_JOB_QUEUE_BACKEND=rq RQ_QUEUE_NAME=langgraph_smoke ... ./.venv/bin/python scripts/run_generation_worker.py
AGENT_WORKFLOW_BACKEND=langgraph GENERATION_JOB_QUEUE_BACKEND=rq RQ_QUEUE_NAME=langgraph_smoke ... uvicorn app.main:app --host 127.0.0.1 --port 8018
curl -X POST http://127.0.0.1:8018/api/v1/test-cases/generation-jobs ...
# job_id=a5ab704ab02a4af1aa498e6af5d68193
# status=failed, error.code=budget_exceeded, record_id=db9663c4af3e4f09aad8db27c954fc38, queue length=0
```

当前 `AGENT_WORKFLOW_BACKEND=langgraph` 为默认值。已新增 `LangGraphGenerationWorkflowRunner` 动态入口，基础依赖和轻量 smoke 依赖均包含 LangGraph；`requirements-langgraph.txt` 保留为兼容入口。`local` backend 保留为 fallback 和行为对照。`langgraph` backend 已完成生成器级、真实服务和 Redis/RQ worker smoke。

LangGraph-first 切换验证：

```bash
./.venv/bin/python -m pytest tests/test_config.py tests/test_deployment_templates.py tests/test_generator.py tests/test_agent_workflow.py -q
# 51 passed, 1 skipped

./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_config.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_runtime_paths.py tests/test_queue_observability.py -q
# 72 passed, 1 skipped

./.venv/bin/python -c "from app.core.config import get_settings; print(get_settings().agent_workflow_backend)"
# langgraph

# Default LangGraph real sync API smoke
# no AGENT_WORKFLOW_BACKEND env var set
# api_port=8024
# response=HTTP 409
# detail.code=budget_exceeded
# record_id=67adb8dba7a04598a4fe3b6fa75f44b4
# generation_records.status=failed
# gate_status=pending

# Default LangGraph Redis/RQ worker smoke
# no AGENT_WORKFLOW_BACKEND env var set for API or worker
# api_port=8025
# queue=default-langgraph-smoke
# job_id=c711ebc66f874a5e95cda65655a32b7a
# status=failed
# error.code=budget_exceeded
# record_id=712f8ced2f224764927d45aa729311cb
# generation_jobs.status=failed
# generation_records.status=failed
# gate_status=pending
# queue_check: health.ok=true, queued=0, started=0, failed=0, finished=1, worker_count=1
```

MySQL Phase 1 验证：

```bash
./.venv/bin/python -m pytest tests/test_config.py tests/test_stores.py tests/test_history.py tests/test_generation_job_store.py tests/test_generation_jobs.py tests/test_deployment_templates.py -q
# 35 passed

./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_ingest_documents.py tests/test_startup_validation.py tests/test_config.py tests/test_quality.py tests/test_usage.py tests/test_reviewer.py tests/test_rag_evaluation.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_models.py tests/test_query_rewrite.py tests/test_rag.py tests/test_stores.py tests/test_mysql_migration.py -q
# 89 passed, 1 skipped, 2 warnings
```

当前 `DATABASE_BACKEND=sqlite` 为默认值。已新增 `GenerationHistoryRepository`、`GenerationJobRepository` 和 store factory；API、Redis/RQ queue、RQ worker、生成执行器已改为依赖 repository protocol 或 factory。`DATABASE_BACKEND=mysql` 代码路径已实现，`.venv` 已安装 `PyMySQL`，`my-mysql` 容器内 schema 已初始化，并完成真实 MySQL smoke。

MySQL schema 脚手架验证：

```bash
./.venv/bin/python -m pytest tests/test_deployment_templates.py tests/test_mysql_migration.py tests/test_config.py tests/test_stores.py -q
# 28 passed
```

已新增 `requirements-mysql.txt`、`migrations/mysql/001_initial.sql` 和 `scripts/init_mysql.py`。Dockerfile 已复制 `requirements-mysql.txt` 和 `migrations/`，后续可用 `REQUIREMENTS_FILE=requirements-mysql.txt` 构建包含 `PyMySQL` 的镜像。

MySQL runtime smoke：

```bash
# MySQL store smoke
# record_id=8739bf45e2754022bc8f5dad0afbde59
# job_id=53c78338800b4d1abb4c6cf63736f56f

# Redis/RQ + MySQL smoke
# job_id=7898d467d1c8498689dae88500f7d9b7
# status=failed, error.code=budget_exceeded
# record_id=01ba8a5b96fa434da56b4ef6b6468d42
# RQ queue length=0

# Redis/RQ + MySQL + API + worker smoke
# mode=local Python API/worker + Docker Redis + Compose MySQL
# mysql_project=agent_mysql_smoke
# mysql_host_port=3307
# queue=generation-mysql-smoke
# job_id=df50848d423d45c69fcc817454955c72
# status=failed, error.code=budget_exceeded
# record_id=8374573ace9c45afb80f88f6d9fd3bf1
# RQ queue length=0, finished_count=1
# MySQL restart persistence check=passed

# MySQL backup/restore rehearsal
# backup_file=/tmp/agent-mysql-backups/agent-smoke-20260624.sql
# source_volume=agent_mysql_smoke_mysql-data
# restore_volume=agent_restore_test_mysql-data
# restored generation_jobs=1, generation_records=1
# restored job_id=df50848d423d45c69fcc817454955c72
# restored record_id=8374573ace9c45afb80f88f6d9fd3bf1
# note=mysqldump requires --no-tablespaces for current business user

# Full Compose API/worker + Redis + MySQL smoke
# project=agent_compose_mysql_smoke
# image=ai-testcase-generator:local
# build_requirements=requirements-mysql.txt
# api_host_port=8021, redis_host_port=6381, mysql_host_port=3309
# queue=generation-compose-smoke
# job_id=f34c9701f1734143bc5c034e86a20f69
# status=failed, error.code=budget_exceeded
# record_id=a31853c1f8b94e1d8019123371db283e
# RQ queue length=0, finished_count=1
# API/worker restart persistence check=passed

# Redis/RQ + MySQL + API + worker stability smoke
# project=agent_stability_mysql
# image=ai-testcase-generator:local
# build_requirements=requirements-mysql.txt
# api_host_port=8022, redis_host_port=6382, mysql_host_port=3310
# queue=generation-compose-smoke
# submitted_jobs=5
# final_status=failed for all jobs
# error.code=budget_exceeded for all jobs
# latest_job_id=f6d85795ef4e4174895e810ca942f0e0
# latest_record_id=0145d159593e4d97b81e05b5526b990b
# MySQL generation_jobs=5, generation_records=5
# MySQL status counts: failed=5 for both tables
# RQ queue_count=0, failed_count=0, finished_count=5
# API/worker restart persistence check=passed
# note=worker service disables inherited Dockerfile HTTP healthcheck
```

Docker runtime hardening：

```bash
./.venv/bin/python -m pytest tests/test_runtime_paths.py tests/test_deployment_templates.py -q
# 8 passed

COMPOSE_PROJECT_NAME=agent_runtime_path_smoke API_HOST_PORT=8023 REDIS_HOST_PORT=6383 \
  docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d --build
# Image ai-testcase-generator:smoke Built
# api status=healthy
# worker status=up
# api logs contain "Runtime path check passed."
# worker logs contain "Runtime path check passed."
# worker listening on generation-compose-smoke

COMPOSE_PROJECT_NAME=agent_full_requirements_build REQUIREMENTS_FILE=requirements.txt INSTALL_ML_DEPS=false \
  docker compose -f docker-compose.yml build api
# Image ai-testcase-generator:local Built
# image size before LangGraph-first switch: ai-testcase-generator:local 762MB
# smoke image size before LangGraph-first switch: ai-testcase-generator:smoke 270MB
# note: requirements.txt and requirements-smoke.txt now include LangGraph; rebuild to confirm new sizes.

COMPOSE_PROJECT_NAME=agent_ml_build IMAGE_TAG=ml REQUIREMENTS_FILE=requirements.txt INSTALL_ML_DEPS=true \
  docker compose -f docker-compose.yml build api
# Image ai-testcase-generator:ml Built
# image size: ai-testcase-generator:ml 2.33GB
# torch=2.12.1+cpu
# torch.cuda.is_available()=False
# sentence_transformers=5.6.0
```

已新增 `scripts/check_runtime_paths.py`，并接入 Dockerfile API 默认启动命令和 Compose worker 命令。容器启动前会检查 `CHROMA_PATH`、`EMBEDDING_CACHE_DIR` 和 SQLite backend 下 `GENERATION_HISTORY_DB_PATH` 父目录是否可写；Linux bind mount 权限错误会在容器日志里明确暴露。

Queue observability：

```bash
./.venv/bin/python -m pytest tests/test_queue_observability.py tests/test_generation_job_store.py tests/test_deployment_templates.py -q
# 18 passed

./.venv/bin/python -m pytest tests/test_queue_observability.py tests/test_generation_job_store.py tests/test_runtime_paths.py tests/test_deployment_templates.py tests/test_config.py tests/test_mysql_migration.py -q
# 42 passed

./.venv/bin/python scripts/check_generation_queue.py --json
# database.backend=sqlite
# database.active_count=0
# queue.backend=in_memory
# health.ok=true

GENERATION_JOB_QUEUE_BACKEND=rq REDIS_URL=redis://127.0.0.1:6379/0 RQ_QUEUE_NAME=generation-compose-smoke \
  ./.venv/bin/python scripts/check_generation_queue.py --json
# health.ok=true
# queue.backend=rq
# queue.name=generation-compose-smoke
# queued=0, started=0, failed=0, finished=0
# worker_count=0
```

已新增 `scripts/check_generation_queue.py`。脚本会读取当前 `Settings`，输出当前数据库 backend 的 `generation_jobs` 状态统计；当 `GENERATION_JOB_QUEUE_BACKEND=rq` 时，会读取 RQ queued/started/finished/failed/deferred/scheduled registry、worker 心跳和队列名，并用数据库 active jobs 与 RQ active registry 做第一版对账。支持 `--json` 和 `--fail-on-mismatch`。当前沙箱禁止直连宿主 Redis socket；非沙箱 Redis/RQ 只读实测已通过。

LangGraph trace deepening：

```bash
./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_generator.py -q
# 24 passed, 1 skipped

./.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_run_server.py tests/test_config.py tests/test_deployment_templates.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_generator.py tests/test_history.py tests/test_runtime_paths.py tests/test_queue_observability.py tests/test_models.py tests/test_quality.py tests/test_reviewer.py -q
# 82 passed, 1 skipped
```

`GenerationMetadata` 已新增 `workflow_backend`；`WorkflowStep` 已新增 `backend` 和结构化 `trace`。LangGraph 和 local fallback 都通过 `WorkflowRecorder` 写入一致格式。`trace` 当前覆盖需求分析、RAG 召回、检索路由、query rewrite、测试策略、Prompt 构建、预算门控、LLM 调用、输出校验、Reviewer、质量门控和 usage 估算等节点。

RAG 全链路质量兜底：

```bash
./.venv/bin/python -m pytest tests/test_quality.py tests/test_reviewer.py tests/test_prompt.py tests/test_generator.py -q
# 33 passed, 1 skipped
```

已将登录模块知识库落盘到 `knowledge/prd/login/default-langgraph-full-chain.md`，并整理为 PRD、账号状态、密码/验证码、token、权限、安全、审计日志和最小覆盖矩阵。当前 v4 collection 中该 source 已 upsert 到 version 4，拆成 4 个 chunk，RAG query 可召回密码边界、验证码不累计、账号枚举、token 泄露和审计日志规则。

当前已进一步拆分登录知识库：

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`
- `knowledge/api/login/login-api-contract.md`
- `knowledge/security/login/login-security-baseline.md`
- `knowledge/audit/login/login-audit-log.md`
- `tests/fixtures/login_rag_eval_cases.json`

隔离 RAG 评估 collection `login_rag_eval_hash` 已验证通过：导入 6 个文档、15 个 chunks，`source_hit_rate=1.0`、`keyword_hit_rate=1.0`、`case_pass_rate=1.0`。

发布检查入口已新增：

```bash
./.venv/bin/python scripts/run_release_checks.py
# login RAG eval + core pytest + git diff --check
# 92 passed, 1 skipped

./.venv/bin/python scripts/run_release_checks.py --include-llm-smoke
# 可选真实 LLM 强门控 smoke，会消耗模型额度
```

CI 已接入 `.github/workflows/ci.yml`：push/PR 默认运行确定性发布检查；真实 LLM 强门控 smoke 仅在 `workflow_dispatch` 且勾选 `run_llm_smoke` 时运行，需要配置 GitHub Secret `ZHIPU_API_KEY`。

真实链路验证记录：

- v4：默认 LangGraph + RAG + 真实 LLM 跑通，`retrieved_chunks=1`，但遗漏 boundary、账号枚举、验证码不累计密码错误次数。
- v5：补结构化知识库后，`retrieved_chunks=3`，类型覆盖齐全，补上密码边界和验证码不累计，但仍漏审计日志、账号枚举、token 泄露等部分安全/审计点。
- v6：将矩阵拆成更细原子场景并使用 `max_cases=16`，`retrieved_chunks=4`，生成 16 条，类型全覆盖，只剩审计字段缺失；质量规则已修正 token 泄露假阳性。
- v7：修正知识库为 17 个原子场景并使用 `max_cases=17`，仍因模型随机性漏 disabled/deleted/审计。结论：补知识库是必要条件，但不足以保证完整覆盖；下一步需要覆盖修复节点或默认强质量门控。
- 覆盖修复：`GenerationReview` 已新增 `missing_target_types` 和 `missing_acceptance_keywords`；Reviewer retry 反馈会生成“覆盖修复要求”，满额时要求替换低价值/泛化用例；`route_after_review` trace 会在结构化缺口存在时标记 `reason=coverage_repair`。若同时开启 `AGENT_REVIEW_RETRY_ENABLED=true` 和 `AGENT_REVIEW_REQUIRE_PASS=true`，重试后仍缺失会返回 `quality_gate_failed` 409。
- 强门控 smoke：使用真实 FastAPI、默认 LangGraph、登录 RAG collection、真实 LLM，开启 `AGENT_REVIEW_RETRY_ENABLED=true` 和 `AGENT_REVIEW_REQUIRE_PASS=true`。小容量不达标请求返回 `HTTP 409`，`detail.code=quality_gate_failed`，结构化返回缺失类型和缺失验收点；足量 20 场景请求返回 `HTTP 200`，第一轮 `route_after_review` 为 `reason=coverage_repair`，第二轮 `review.passed=true`、`score=98`、`missing_acceptance_keywords=[]`。

## 当前限制

- SQLite 适合单机，不适合高并发或多主机共享任务状态；MySQL backend 已可用，Compose MySQL 模板、运维文档、恢复演练、完整 Compose smoke 和多任务稳定性 smoke 已通过，但默认仍是 `sqlite`。
- Docker 轻量 Redis/RQ smoke、`requirements-mysql.txt` 完整 Compose smoke、`requirements.txt` 基础完整镜像构建和 `INSTALL_ML_DEPS=true IMAGE_TAG=ml` CPU-only 语义 embedding 镜像构建已验证；API/worker 运行目录权限检查已接入。
- 队列可观测性脚本已补齐基本检查和对账；仍缺 worker crash、Redis/MySQL 短暂不可用和 stale recovery 的故障恢复实测。
- LangGraph 当前是默认 backend，基础镜像和轻量 smoke 镜像都安装 LangGraph；`workflow_steps` 已补结构化 trace。后续增强重点是 checkpoint、interrupt、人审节点和外部 trace viewer，`local` backend 保留为回滚路径。
- RAG 登录知识库已补成结构化验收矩阵；Reviewer 缺口已能转成覆盖修复反馈，强质量门控也能拦截重试后仍缺失的结果。后续重点是固定评估集和批量质量验证，而不是继续手工跑单个登录请求。
- Linux bind mount 下如果宿主 `./data` 是 `root:root` 且 755，非 root 容器用户会因 SQLite 只读启动失败；smoke compose 已改用 named volume 避免该问题。
- 当前环境 FastAPI `TestClient` 仍会卡住，API 级验证优先使用真实 uvicorn/curl 或 Compose smoke。

## 下一阶段建议

推荐下一步：

1. 继续队列故障恢复验证：worker crash、Redis 短暂不可用、MySQL 短暂不可用、任务 stale recovery。
2. 评估是否将发布检查脚本作为 pre-push 或 CI 必选门禁。
3. 继续补更多模块的 RAG 固定评估集。
