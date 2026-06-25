# 部署说明

这份文档用于说明项目的本地运行、容器运行和发布前配置要求。当前项目适合做个人项目、内网服务、受控测试环境或小型系统集成，不建议直接裸露到公网。

## 1. 必要配置

生产或准生产环境必须通过环境变量提供配置，不要把真实 key 写入仓库。

```text
APP_ENV=production
APP_API_KEY=replace-with-strong-service-api-key
ZHIPU_API_KEY=replace-with-real-zhipu-key
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_CHAT_MODEL=glm-4-flash
CHROMA_PATH=data/chroma
CHROMA_COLLECTION=test_knowledge_bge_small_zh_v15
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_CACHE_DIR=.model_cache/huggingface
EMBEDDING_DEVICE=cpu
EMBEDDING_LOCAL_FILES_ONLY=true
LLM_MAX_RETRIES=2
LLM_TIMEOUT_SECONDS=60
LLM_PROMPT_PRICE_PER_1K_TOKENS=0
LLM_COMPLETION_PRICE_PER_1K_TOKENS=0
LLM_COST_CURRENCY=CNY
AGENT_REVIEW_ENABLED=true
AGENT_REVIEW_RETRY_ENABLED=false
AGENT_REVIEW_MIN_SCORE=50
AGENT_REVIEW_REQUIRE_PASS=false
AGENT_QUERY_REWRITE_ENABLED=true
AGENT_QUERY_REWRITE_MIN_CHUNKS=1
AGENT_BUDGET_MAX_PROMPT_TOKENS=0
AGENT_BUDGET_MAX_ESTIMATED_COST=0
AGENT_WORKFLOW_BACKEND=langgraph
GENERATION_JOB_QUEUE_BACKEND=rq
GENERATION_JOB_MAX_WORKERS=2
GENERATION_JOB_MAX_QUEUE_SIZE=100
GENERATION_JOB_RETENTION_SECONDS=3600
REDIS_URL=redis://redis:6379/0
RQ_QUEUE_NAME=generation
RQ_JOB_TIMEOUT_SECONDS=900
RQ_RESULT_TTL_SECONDS=3600
RQ_FAILURE_TTL_SECONDS=86400
GENERATION_JOB_STALE_AFTER_SECONDS=1800
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
REQUEST_LOG_ENABLED=true
DATABASE_BACKEND=sqlite
# DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
GENERATION_HISTORY_ENABLED=true
GENERATION_HISTORY_DB_PATH=data/app.sqlite3
RUNTIME_PATH_CHECK_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
CORS_ALLOW_CREDENTIALS=false
```

本地仍兼容读取 `.env/config.py`，但这个目录已经被 `.gitignore` 排除，不应提交。

当 `APP_ENV=production` 时，服务会在启动阶段强制校验生产配置。以下情况会直接拒绝启动：缺少真实 `APP_API_KEY` 或 `ZHIPU_API_KEY`、CORS 使用 `*` 或本地地址、CORS 非 HTTPS、`EMBEDDING_PROVIDER=hash`、`EMBEDDING_LOCAL_FILES_ONLY=false`、关闭限流、关闭请求日志、关闭 Agent Reviewer、关闭生成历史、历史库使用内存路径。

## 2. 本地运行

Linux 本机推荐使用 Docker Redis + 本机 Python API/worker，完整步骤见 [本机运行基线](local-run.md)。关键区别是：本机 Python 进程使用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 容器内部使用 `REDIS_URL=redis://redis:6379/0`。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run_server.py --host 127.0.0.1 --port 8000
```

控制台启动会直接显示 uvicorn 输出。需要后台启动时使用：

```powershell
scripts\start_server.cmd
```

后台启动日志写入 `logs/server.out.log` 和 `logs/server.err.log`。

## 3. Docker 运行

推荐使用 Docker Compose。先基于示例创建本机运行配置：

```powershell
Copy-Item .env.runtime.example .env.runtime
```

然后编辑 `.env.runtime`，替换真实服务密钥、模型密钥和前端 HTTPS 域名。启动服务：

```powershell
docker compose up -d --build
docker compose ps
```

Docker 镜像默认安装基础依赖、Redis/RQ 和 LangGraph，适合 `EMBEDDING_PROVIDER=hash` 的本地验证和 Redis/RQ smoke test。生产或准生产如果使用 `EMBEDDING_PROVIDER=sentence_transformers`，构建镜像时需要安装额外 ML 依赖。建议给 ML 镜像使用独立 tag，避免覆盖基础镜像：

```powershell
$env:IMAGE_TAG="ml"
$env:INSTALL_ML_DEPS="true"
docker compose build
docker compose up -d
```

Linux shell 等价命令：

```bash
IMAGE_TAG=ml INSTALL_ML_DEPS=true docker compose build
IMAGE_TAG=ml INSTALL_ML_DEPS=true docker compose up -d
```

Dockerfile 默认使用 `pip` 安装依赖，减少构建阶段的额外下载点。如果本机网络和缓存条件较好，也可以显式使用 `uv`：

```bash
INSTALLER=uv docker compose build
```

Redis/RQ smoke test 不需要 RAG 依赖。为避免验证队列时下载 `chromadb`、`numpy`、`onnxruntime` 等较重依赖，可以使用轻量依赖构建：

```bash
docker compose -f docker-compose.yml -f docker-compose.smoke.yml build
docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
```

如果本机已有 Redis 容器占用 `6379`，可以把 compose Redis 暴露到另一个本机端口：

```bash
REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
```

注意：compose 容器内部仍使用 `REDIS_URL=redis://redis:6379/0`，`REDIS_HOST_PORT` 只影响宿主机访问 compose Redis 的端口。

轻量 smoke compose 会把 `/app/data` 和模型缓存目录改成 Docker named volume，避免 Linux 下宿主 `./data` 属主不匹配导致 SQLite 只读。

当前已验证的镜像构建路径：

- `requirements-smoke.txt` 轻量 smoke 镜像：切到默认 LangGraph 前的构建记录约 `270MB`；加入 LangGraph 依赖后需重建确认新体积。
- `requirements.txt` 基础完整镜像：切到默认 LangGraph 前的构建记录约 `762MB`；加入 LangGraph 依赖后需重建确认新体积，包含 Chroma/RAG 基础依赖。
- `INSTALL_ML_DEPS=true IMAGE_TAG=ml` 语义 embedding 镜像：约 `2.33GB`，使用 `torch==2.12.1+cpu`，容器内验证 `torch.cuda.is_available()` 为 `False`。

`requirements-ml.txt` 使用 PyTorch CPU wheel index。不要直接改回宽松的 `torch>=...`，否则 Linux 构建可能从默认 PyPI 拉取 CUDA wheel，并额外解析 `nvidia-*`、`cuda-toolkit` 等大体积依赖。

`docker-compose.yml` 会挂载 `./data:/app/data` 和 `./.model_cache/huggingface:/app/.model_cache/huggingface`，并通过 `/health` 做容器健康检查。
Linux 部署时要确认这两个宿主目录对容器内 `appuser` 可写；如果目录由 `root` 创建且权限是 755，worker 会因为 SQLite 只读而启动失败。

API 和 worker 容器启动时会先执行 `scripts/check_runtime_paths.py`，检查 `CHROMA_PATH`、`EMBEDDING_CACHE_DIR`，以及 SQLite backend 下 `GENERATION_HISTORY_DB_PATH` 的父目录是否可创建和写入。权限不正确时容器会直接退出，并在日志里输出具体目录。

可以先手动检查运行目录：

```bash
docker compose run --rm api python scripts/check_runtime_paths.py
```

启动后可以检查生成队列、worker 心跳和数据库任务状态：

```bash
docker compose exec api python scripts/check_generation_queue.py --fail-on-mismatch
```

如果需要机器可读输出：

```bash
docker compose exec api python scripts/check_generation_queue.py --json
```

Linux bind mount 权限修复示例：

```bash
mkdir -p data .model_cache/huggingface
docker compose run --rm --entrypoint id api
sudo chown -R 1000:1000 data .model_cache
sudo chmod -R u+rwX data .model_cache
```

如果 `id` 命令显示的 appuser uid/gid 不是 `1000:1000`，按实际值替换。只有在确认目录由外部只读介质提供且不会写入时，才考虑设置 `RUNTIME_PATH_CHECK_ENABLED=false` 跳过检查；常规部署不建议关闭。

也可以手动构建镜像：

```powershell
docker build --build-arg INSTALL_ML_DEPS=true -t ai-testcase-generator .
```

手动运行镜像：

```powershell
docker run --rm -p 8000:8000 `
  --env-file .env.runtime `
  -v ${PWD}\data:/app/data `
  -v ${PWD}\.model_cache\huggingface:/app/.model_cache/huggingface `
  ai-testcase-generator
```

`.env.runtime` 只放在本机，不提交到仓库。容器镜像不会包含 `.env/`、`.model_cache/`、`data/chroma/`、`logs/` 或 `knowledge_export/`。

生成历史和异步任务状态默认使用 `DATABASE_BACKEND=sqlite` 并写入 `data/app.sqlite3`。如果使用 Docker，必须挂载 `/app/data` 或单独挂载 SQLite 文件所在目录，否则容器删除后历史记录会丢失。需要切换到 MySQL 时，先初始化 schema，再设置 `DATABASE_BACKEND=mysql` 和 `DATABASE_URL`。

本机 Python 直连 Docker MySQL 时，需要先安装可选依赖并初始化 schema：

```bash
uv pip install --python ./.venv/bin/python -r requirements-mysql.txt
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/init_mysql.py
```

Compose 运行 MySQL 时，复制 `.env.runtime.example` 为 `.env.runtime` 后需要设置 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`，并将数据库配置改为：

```env
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
```

然后使用 MySQL override 启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d --build
```

`docker-compose.mysql.yml` 会启动 `mysql:8.0`，挂载 `mysql-data` volume，并在新 volume 首次初始化时执行 `migrations/mysql/001_initial.sql`。该 override 带有可解析的占位默认值；正式使用时应通过 shell 环境变量或 Compose 自动读取的 `.env` 文件覆盖 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD` 和 `DATABASE_URL`，并保持 `.env.runtime` 中的数据库配置一致。如果 volume 已存在，MySQL 不会重新执行初始化脚本，也不会按新的 `MYSQL_*` 环境变量重置旧密码或旧数据。

容器构建时 MySQL override 会使用 `REQUIREMENTS_FILE=requirements-mysql.txt` 安装 `PyMySQL`。本机 Python 直连 Docker MySQL 时使用 `127.0.0.1:3306`，Compose 容器内部使用服务名 `mysql:3306`。初始化、备份、恢复和恢复演练步骤见 [MySQL 初始化、备份与恢复](mysql-operations.md)。当前 MySQL backend 已通过本机 Docker MySQL store smoke、Redis/RQ worker smoke、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke；生产默认切换前仍建议补 worker crash、Redis/MySQL 短暂不可用和更长时长运行验证。

## 4. 知识库导入

首次部署后需要导入知识库：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py knowledge knowledge_export --recursive --reset
```

如果是公开 GitHub 仓库，不要提交 `knowledge_export/`。它来自你的真实项目，默认应作为私有数据保留在本地或部署环境。

导入后运行 RAG 评估：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --top-k 5
```

登录模块可使用隔离 collection 做固定评估。Linux / WSL 示例：

```bash
EMBEDDING_PROVIDER=hash CHROMA_PATH=data/chroma-login-rag-eval CHROMA_COLLECTION=login_rag_eval_hash \
  ./.venv/bin/python scripts/ingest_documents.py \
  knowledge/prd/login knowledge/api/login knowledge/security/login knowledge/audit/login \
  --recursive --reset --chunk-size 900

EMBEDDING_PROVIDER=hash CHROMA_PATH=data/chroma-login-rag-eval CHROMA_COLLECTION=login_rag_eval_hash \
  ./.venv/bin/python scripts/evaluate_rag.py \
  --cases tests/fixtures/login_rag_eval_cases.json \
  --top-k 5 \
  --case-keyword-ratio 1.0 \
  --fail-under-source-hit-rate 1.0 \
  --fail-under-keyword-hit-rate 1.0
```

## 5. 发布检查

初始化仓库前先确认这些路径不会提交：

```powershell
git init
git status --ignored
```

应保持忽略：

```text
.env/
.env.*
.venv/
.model_cache/
data/chroma/
logs/
exports/
knowledge_export/
__pycache__/
.pytest_cache/
```

推荐先提交代码、测试、文档和示例配置，不提交真实 key、模型缓存、向量库数据、运行日志和私有知识库。

## 6. 上线前检查

- `.\.venv\Scripts\python.exe -m pytest -q` 必须通过。
- `/health` 可访问。
- 生产环境必须设置 `APP_ENV=production`，并确保启动配置校验通过。
- 所有 `/api/v1/*` 接口必须携带 `X-API-Key`。
- `CORS_ALLOW_ORIGINS` 必须配置为真实前端域名，不使用 `*`。
- 应用内 `RATE_LIMIT_*` 必须按真实调用量调整；公网环境仍建议在网关层做限流。
- 异步生成队列建议使用 `GENERATION_JOB_QUEUE_BACKEND=rq` 和 Redis/RQ；本机 Python 直连 Docker Redis 时使用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 内部使用 `REDIS_URL=redis://redis:6379/0`。
- 上线前运行 `scripts/check_generation_queue.py --fail-on-mismatch`，确认 RQ active registry 与数据库 `queued/running` 任务没有明显不一致。
- `GENERATION_JOB_MAX_QUEUE_SIZE` 必须按模型限流和机器资源设置；默认 SQLite 任务状态适合单机和低并发，多实例部署应使用 MySQL backend，并补原子背压和稳定性验证。
- `GENERATION_JOB_STALE_AFTER_SECONDS` 应大于正常最长生成耗时；worker 启动时会把超过该阈值仍处于 `running` 的任务标记为失败。
- `RUNTIME_PATH_CHECK_ENABLED=true` 时，容器启动前会检查 Chroma、模型缓存和 SQLite 历史库目录的可写性。
- `AGENT_REVIEW_ENABLED` 必须保持开启；是否启用 `AGENT_REVIEW_RETRY_ENABLED` 取决于成本预算和质量门槛。
- 如需强成本控制，设置 `AGENT_BUDGET_MAX_PROMPT_TOKENS` 或 `AGENT_BUDGET_MAX_ESTIMATED_COST`；如需强质量门禁，设置 `AGENT_REVIEW_REQUIRE_PASS=true`。
- 默认可以使用 `DATABASE_BACKEND=sqlite`；`GENERATION_HISTORY_DB_PATH` 所在目录必须持久化，并纳入备份策略。多实例或更高并发部署应改用 `DATABASE_BACKEND=mysql`。
- `APP_API_KEY` 和 `ZHIPU_API_KEY` 必须来自环境变量或部署密钥管理。
- Chroma 数据目录需要持久化备份。
- 模型缓存目录需要放在 D 盘或部署机器的数据盘，避免写入系统盘。
- 对外暴露前应增加网关限流、访问日志、错误监控和 HTTPS。
