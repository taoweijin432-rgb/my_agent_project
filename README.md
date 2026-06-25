# AI 测试用例生成助手

AI 测试用例生成助手是一个个人开发的测试工程辅助项目，用于将自然语言需求、PRD 或历史用例知识库转换为结构化测试用例。服务通过 FastAPI 暴露 REST API，使用 LangGraph 编排生成链路，通过 Chroma 检索知识库，并调用智谱大模型 JSON Mode 生成可导出、可审查的测试用例。

## 项目状态

当前版本是可运行的 LangGraph + RAG 测试用例生成基线，已经包含 API 服务、知识库检索、测试用例生成、Reviewer 质量审查、质量门控、异步任务、Redis/RQ worker、SQLite/MySQL 存储、Docker/Compose 和 CI 发布检查。

已验证的基线：

- 发布检查：登录 RAG 固定评估、核心 pytest 回归、`git diff --check`。
- 真实链路 smoke：FastAPI + LangGraph + RAG + LLM + Reviewer 覆盖修复 + 质量门控。
- CI：push / pull request 执行确定性检查，手动 workflow 可选择真实 LLM smoke。

生产环境使用前仍建议补充权限模型、审计闭环、监控告警、数据迁移策略、密钥管理和完整业务知识库。

## 相关文档

- [项目说明](docs/project-guide.md)
- [架构基线](docs/architecture-baseline.md)
- [Agent 架构](docs/agent-architecture.md)
- [本机运行](docs/local-run.md)
- [部署说明](docs/deployment.md)
- [发布检查](docs/release-checklist.md)
- [RAG 评估](docs/rag-evaluation.md)
- [MySQL 运维说明](docs/mysql-operations.md)

## 功能

- `POST /api/v1/test-cases/generate`：输入需求描述，返回结构化测试用例。
- `POST /api/v1/test-cases/generation-jobs`：提交异步生成任务，适合长需求或批量调用。
- `GET /api/v1/test-cases/generation-jobs`：查询异步生成任务列表。
- `GET /api/v1/test-cases/generation-jobs/{job_id}`：查询异步生成任务详情和结果。
- `POST /api/v1/test-cases/export`：将测试用例导出为 Excel。
- `POST /api/v1/knowledge/ingest`：导入 PRD、历史用例等知识文本到 Chroma。
- `POST /api/v1/knowledge/query`：验证知识库检索结果。
- `GET /api/v1/knowledge/documents`：查看知识库文档清单和当前版本。
- `POST /api/v1/knowledge/documents/upsert`：按 `source` 更新或新增单个知识库文档。
- `DELETE /api/v1/knowledge/documents?source=...`：按 `source` 删除知识库文档。
- `GET /api/v1/generation-records`：查询生成历史记录。
- `GET /api/v1/generation-records/{record_id}`：查询单次生成详情。
- `GET /api/v1/generation-gates`：查询预算或质量门控触发的待人工处理记录。
- `POST /api/v1/generation-gates/{record_id}/resolve`：审批或驳回门控记录。

测试用例字段固定为：

```json
{
  "id": "TC-001",
  "title": "用例标题",
  "precondition": "前置条件",
  "steps": ["步骤 1", "步骤 2"],
  "expected": ["预期结果 1", "预期结果 2"],
  "type": "functional"
}
```

`type` 可选值：`functional`、`boundary`、`exception`、`permission`、`compatibility`、`performance`、`security`。

## 运行命令

以下命令默认在项目根目录执行。

安装依赖：

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

准备本机环境变量：

```bash
cp .env.runtime.example .env.runtime
```

编辑 `.env.runtime`，至少替换 `APP_API_KEY` 和 `ZHIPU_API_KEY`。不要提交真实密钥。

启动 API：

```bash
./.venv/bin/python scripts/run_server.py --host 127.0.0.1 --port 8000
```

也可以直接使用 uvicorn：

```bash
./.venv/bin/python -m uvicorn app.main:app --reload
```

打开接口文档：

```text
http://127.0.0.1:8000/docs
```

导入知识库：

```bash
./.venv/bin/python scripts/ingest_documents.py knowledge --recursive --reset
```

启动 Redis/RQ worker：

```bash
GENERATION_JOB_QUEUE_BACKEND=rq REDIS_URL=redis://127.0.0.1:6379/0 ./.venv/bin/python scripts/run_generation_worker.py
```

提交前发布检查：

```bash
./.venv/bin/python scripts/run_release_checks.py
```

更多发布检查说明见 [发布检查](#发布检查)。

需要验证真实 LangGraph + RAG + LLM + 质量门控时，手动运行：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-smoke
```

该模式会调用真实模型并消耗额度。

Windows PowerShell 可使用同等命令：

```powershell
python scripts/run_server.py --host 127.0.0.1 --port 8000
```

Windows 后台启动并写入日志：

```powershell
scripts\start_server.cmd
```

## 发布检查

本地发布或提交前建议运行：

```bash
./.venv/bin/python scripts/run_release_checks.py
```

默认会执行登录 RAG 固定评估、核心测试回归和 `git diff --check`，不会调用真实 LLM。

需要验证真实 LangGraph + RAG + LLM + 质量门控时，手动运行：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-smoke
```

该模式会调用真实模型并消耗额度。

## CI

仓库内置 GitHub Actions 配置：[.github/workflows/ci.yml](.github/workflows/ci.yml)。

默认 CI 在 push 和 pull request 时执行确定性发布检查：

- 登录 RAG 固定评估。
- 核心 pytest 回归。
- `git diff --check`。

真实 LLM 质量门控 smoke 不在默认 CI 中运行。需要时在 GitHub Actions 手动触发 `CI` workflow，勾选 `run_llm_smoke`，并在仓库 Secrets 中配置：

```text
ZHIPU_API_KEY
```

## Docker

镜像运行：

```powershell
docker build -t ai-testcase-generator .
docker run --rm -p 8000:8000 --env-file .env.runtime ai-testcase-generator
```

也可以使用 Docker Compose。先基于 `.env.runtime.example` 准备本机 `.env.runtime`，替换真实密钥和域名后启动：

```powershell
docker compose up -d --build
docker compose ps
```

如果在 Linux 本机运行 API/worker，并复用 Docker Redis，按 [docs/local-run.md](docs/local-run.md) 操作。注意本机 Python 进程使用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 容器内部才使用 `REDIS_URL=redis://redis:6379/0`。

Redis/RQ smoke test 可使用轻量 compose 覆盖文件，避免下载 RAG 相关重依赖：

```bash
docker compose -f docker-compose.yml -f docker-compose.smoke.yml build
REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
```

该 smoke 环境会启动 API、worker 和 Redis；预算门控配置会让异步任务最终以 `error.code=budget_exceeded` 结束，用于验证 Redis/RQ 闭环且避免真实 LLM 调用。

## 配置

优先读取系统环境变量：

```text
APP_API_KEY
APP_ENV
ZHIPU_API_KEY
ZHIPU_BASE_URL
ZHIPU_CHAT_MODEL
CHROMA_PATH
CHROMA_COLLECTION
EMBEDDING_PROVIDER
EMBEDDING_MODEL
EMBEDDING_CACHE_DIR
EMBEDDING_DEVICE
EMBEDDING_LOCAL_FILES_ONLY
LLM_MAX_RETRIES
LLM_TIMEOUT_SECONDS
LLM_PROMPT_PRICE_PER_1K_TOKENS
LLM_COMPLETION_PRICE_PER_1K_TOKENS
LLM_COST_CURRENCY
AGENT_REVIEW_ENABLED
AGENT_REVIEW_RETRY_ENABLED
AGENT_REVIEW_MIN_SCORE
AGENT_REVIEW_REQUIRE_PASS
AGENT_QUERY_REWRITE_ENABLED
AGENT_QUERY_REWRITE_MIN_CHUNKS
AGENT_BUDGET_MAX_PROMPT_TOKENS
AGENT_BUDGET_MAX_ESTIMATED_COST
AGENT_WORKFLOW_BACKEND
GENERATION_JOB_QUEUE_BACKEND
GENERATION_JOB_MAX_WORKERS
GENERATION_JOB_MAX_QUEUE_SIZE
GENERATION_JOB_RETENTION_SECONDS
REDIS_URL
RQ_QUEUE_NAME
RQ_JOB_TIMEOUT_SECONDS
RQ_RESULT_TTL_SECONDS
RQ_FAILURE_TTL_SECONDS
GENERATION_JOB_STALE_AFTER_SECONDS
RATE_LIMIT_ENABLED
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
REQUEST_LOG_ENABLED
DATABASE_BACKEND
DATABASE_URL
GENERATION_HISTORY_ENABLED
GENERATION_HISTORY_DB_PATH
CORS_ALLOW_ORIGINS
CORS_ALLOW_CREDENTIALS
```

当前项目中已有 `.env/config.py`，服务会兼容读取其中的服务调用密钥、模型 API Key 和 Base URL。不要把真实密钥提交到版本库。

除 `/health` 外，业务接口需要在请求头携带服务调用密钥：

```text
X-API-Key: your-service-api-key
```

应用默认对 `/api/v1/*` 启用内存级限流：每个调用方每 60 秒最多 60 次请求。可以通过 `RATE_LIMIT_ENABLED`、`RATE_LIMIT_REQUESTS` 和 `RATE_LIMIT_WINDOW_SECONDS` 调整。公网部署时仍建议在 API 网关或反向代理层增加限流、HTTPS 和访问日志。

生成接口默认会把请求、响应摘要、完整响应 JSON、失败原因和耗时写入 SQLite：`DATABASE_BACKEND=sqlite`、`GENERATION_HISTORY_DB_PATH=data/app.sqlite3`。该数据库属于运行数据，已被 `.gitignore` 排除；部署时应挂载到持久化数据盘。需要使用 Docker MySQL 时，设置 `DATABASE_BACKEND=mysql` 和 `DATABASE_URL=mysql://agent_user:password@127.0.0.1:3306/agent?charset=utf8mb4`，并按 [docs/mysql-operations.md](docs/mysql-operations.md) 初始化 schema。

生产环境应设置 `APP_ENV=production`。服务启动时会强制校验关键配置：真实 `APP_API_KEY`、真实 `ZHIPU_API_KEY`、HTTPS CORS 来源、非 `hash` embedding、启用本地模型文件、启用限流、启用请求日志、启用 Agent Reviewer、启用生成历史和持久化历史库路径。校验失败会直接拒绝启动。

RAG 默认使用本地 `hash` embedding，便于无模型启动。需要切换到轻量中文语义模型时，可以配置：

```text
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_CACHE_DIR=.model_cache/huggingface
EMBEDDING_DEVICE=cpu
EMBEDDING_LOCAL_FILES_ONLY=true
```

不同 embedding 维度不能混用同一个 Chroma collection。切换模型时建议同步更换 `CHROMA_COLLECTION`，例如 `test_knowledge_bge_small_zh_v15`。

生成链路默认开启本地 query rewrite。初次 RAG 召回少于 `AGENT_QUERY_REWRITE_MIN_CHUNKS` 时，系统会用需求、关注类型、风险类型和测试关键词扩展检索 query，并再检索一次。该过程不调用 LLM。

`AGENT_WORKFLOW_BACKEND` 当前默认使用 `langgraph`，生成链路以 LangGraph 负责编排节点、条件边和重试路径。项目仍保留 `local` backend，作为无框架 fallback 和行为对照实现。基础依赖和轻量 smoke 依赖均已包含 LangGraph；`requirements-langgraph.txt` 保留为兼容入口。

## 导入知识库

通过 API 导入：

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/ingest `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-service-api-key" `
  -d "{\"documents\":[{\"source\":\"prd-login.md\",\"content\":\"手机号验证码登录，验证码 6 位数字，5 分钟有效。\"}]}"
```

通过脚本导入本地文档：

```powershell
python scripts/ingest_documents.py docs/prd-login.md docs/history-cases.md
```

推荐把真实知识库文档放到 `knowledge/` 后递归导入：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py knowledge --recursive --reset
```

`knowledge/` 的一级目录会作为 `document_type`，二级目录会作为 `module` 写入检索 metadata。

如果已经从目标项目整理出 `knowledge_export/`，可以一起导入：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py knowledge knowledge_export --recursive --reset
```

评估 RAG 检索质量：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --top-k 5
```

日常维护单个文档时，优先使用 upsert 接口。它会先删除同 `source` 的旧 chunk，再写入新 chunk，并把文档版本号加 1：

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/documents/upsert `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-service-api-key" `
  -d "{\"document\":{\"source\":\"knowledge/prd/login.md\",\"content\":\"新的登录规则\",\"document_type\":\"prd\",\"module\":\"login\",\"tags\":[\"prd\",\"login\"]},\"chunk_size\":900}"
```

查看当前知识库文档清单：

```powershell
curl -X GET "http://127.0.0.1:8000/api/v1/knowledge/documents?limit=100&offset=0" `
  -H "X-API-Key: your-service-api-key"
```

删除某个文档：

```powershell
curl -X DELETE "http://127.0.0.1:8000/api/v1/knowledge/documents?source=knowledge/prd/login.md" `
  -H "X-API-Key: your-service-api-key"
```

## 生成测试用例

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/test-cases/generate `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-service-api-key" `
  -d "{\"description\":\"用户可以使用手机号和验证码登录系统。验证码 6 位数字，5 分钟有效，错误 5 次后锁定 10 分钟。\",\"max_cases\":8,\"knowledge_top_k\":5}"
```

返回示例：

```json
{
  "cases": [
    {
      "id": "TC-001",
      "title": "有效手机号和验证码登录成功",
      "precondition": "用户已注册，验证码未过期。",
      "steps": ["输入已注册手机号", "输入正确 6 位验证码", "点击登录"],
      "expected": ["登录成功", "进入系统首页"],
      "type": "functional"
    }
  ],
  "metadata": {
    "model": "glm-4-flash",
    "attempts": 1,
    "retrieved_chunks": 1
  },
  "retrieved_context": []
}
```

查询生成历史：

```powershell
curl -X GET "http://127.0.0.1:8000/api/v1/generation-records?limit=20&offset=0" `
  -H "X-API-Key: your-service-api-key"
```

返回的历史摘要包含 `id`、`created_at`、`status`、`description`、`case_count`、`duration_ms`、`model`、`retrieved_sources` 等字段；详情接口会额外返回原始请求、生成响应和 `quality` 质量报告。

`quality` 是本地规则评分，不会调用大模型。评分维度包括用例数量、标题重复率、目标类型覆盖、步骤/预期完整度、是否有知识库召回来源。它适合用于历史回放、质量趋势和人工审核辅助，不等同于最终验收结论。

生成链路内置 `review_cases` Reviewer 节点，成功响应的 `metadata.review` 会返回本地审查结论。默认 `AGENT_REVIEW_ENABLED=true`、`AGENT_REVIEW_RETRY_ENABLED=false`，即记录审查结果但不额外消耗 LLM 调用；如果显式开启自动重试，审查分数低于 `AGENT_REVIEW_MIN_SCORE` 时会把 Reviewer 反馈写入下一轮 Prompt。

生成链路还内置门控节点。`check_budget` 会在调用 LLM 前估算 prompt token 和费用；默认 `AGENT_BUDGET_MAX_PROMPT_TOKENS=0`、`AGENT_BUDGET_MAX_ESTIMATED_COST=0` 表示不阻断。显式设置阈值后，超限请求会返回 409 并写入失败历史。`AGENT_REVIEW_REQUIRE_PASS=true` 时，Reviewer 未通过的结果不会直接返回，需要人工确认或调整输入。

门控失败的 409 响应是结构化的 human-in-the-loop 信号，`detail` 包含 `code`、`gate`、`message`、`action_required`、`usage` 和可选 `review`。调用方可以据此展示审批、人工复核或降低成本后重试。

门控失败也会写入生成历史，并可通过 `GET /api/v1/generation-gates` 拉取待处理列表。该接口默认返回 `pending` 状态；需要查看全部门控记录时使用 `?status=all`，查看已处理记录时使用 `?status=approved` 或 `?status=rejected`。

处理门控记录：

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/generation-gates/{record_id}/resolve" `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-service-api-key" `
  -d "{\"decision\":\"approved\",\"resolved_by\":\"qa-owner\",\"comment\":\"允许继续处理\"}"
```

`decision` 只能是 `approved` 或 `rejected`。已处理的门控记录不会再次被覆盖，重复处理会返回 409。

异步生成入口适合长需求和批量调用：

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/test-cases/generation-jobs `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-service-api-key" `
  -d "{\"description\":\"生成 JWT 登录测试用例\",\"max_cases\":8}"
```

提交成功返回 202 和 `job_id`，调用方再查询任务详情：

```powershell
curl -X GET "http://127.0.0.1:8000/api/v1/test-cases/generation-jobs/{job_id}" `
  -H "X-API-Key: your-service-api-key"
```

任务状态包括 `queued`、`running`、`succeeded`、`failed`。默认 `GENERATION_JOB_QUEUE_BACKEND=in_memory` 会使用进程内队列，适合本地开发和单机演示；设置 `GENERATION_JOB_QUEUE_BACKEND=rq` 后会使用 Redis/RQ 外部队列，并把任务状态写入当前数据库 backend。当前 `DATABASE_BACKEND=sqlite` 会写入 `GENERATION_HISTORY_DB_PATH` 指向的 SQLite 数据库。`GENERATION_JOB_MAX_QUEUE_SIZE` 控制提交背压，队列满会返回 429。worker 启动时会按 `GENERATION_JOB_STALE_AFTER_SECONDS` 把超时停留在 `running` 的任务标记为失败，避免任务永久卡住。直接在 WSL/本机 Python 运行时可使用 `REDIS_URL=redis://127.0.0.1:6379/0`；在 Docker Compose 内运行时使用 `REDIS_URL=redis://redis:6379/0`。

生成响应和历史记录还会返回 `usage`。当前 usage 是本地估算值，包含 prompt/output 字符数、估算 token 数和可选估算费用。默认不计算费用；如果配置 `LLM_PROMPT_PRICE_PER_1K_TOKENS` 与 `LLM_COMPLETION_PRICE_PER_1K_TOKENS`，服务会按每千 token 单价计算 `estimated_cost`。

## 集成方式

其他项目可以直接调用 REST API。生成接口返回稳定 JSON，导出接口返回 Excel 文件流；后续对接禅道、TestRail 或内部测试平台时，只需要在适配层把 `cases` 转换成目标平台字段。
