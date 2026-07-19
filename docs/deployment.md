# 部署说明

这份文档用于说明项目的本地运行、容器运行和发布前配置要求。当前项目适合做个人项目、内网服务、受控测试环境或小型系统集成，不建议直接裸露到公网。

## 1. 必要配置

生产或准生产环境必须通过环境变量提供配置，不要把真实 key 写入仓库。

```text
APP_ENV=production
APP_API_KEY=replace-with-strong-service-api-key
# APP_API_KEYS=current-strong-service-api-key,next-strong-service-api-key
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
LLM_RETRY_BACKOFF_SECONDS=0
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
REQUEST_LOG_FORMAT=json
TEST_TOOL_HTTP_BASE_URL_ALLOWLIST=https://api-under-test.example.com
TEST_TOOL_HTTP_ALLOWED_HEADERS=Accept,Content-Type,X-Request-ID
TEST_TOOL_PYTEST_ENABLED=false
TEST_TOOL_PYTEST_ALLOWED_PATHS=tests
TEST_TOOL_PYTEST_ENV_ALLOWLIST=PATH,PYTHONPATH
DATABASE_BACKEND=sqlite
# DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
MYSQL_CONNECT_TIMEOUT_SECONDS=10
MYSQL_READ_TIMEOUT_SECONDS=30
MYSQL_WRITE_TIMEOUT_SECONDS=30
GENERATION_HISTORY_ENABLED=true
GENERATION_HISTORY_DB_PATH=data/app.sqlite3
RUNTIME_PATH_CHECK_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
CORS_ALLOW_CREDENTIALS=false
```

本地仍兼容读取 `.env/config.py`，但这个目录已经被 `.gitignore` 排除，不应提交。

`APP_API_KEY` 是兼容旧部署的单服务密钥；需要滚动轮换时，推荐使用逗号分隔的 `APP_API_KEYS` 同时配置当前 key 和下一把 key。服务会接受 `APP_API_KEY` 与 `APP_API_KEYS` 中的任意一个值。

当 `APP_ENV=production` 时，服务会在启动阶段强制校验生产配置。以下情况会直接拒绝启动：缺少真实 `APP_API_KEY`/`APP_API_KEYS` 或 `ZHIPU_API_KEY`、服务 key 使用占位值或少于 16 个字符、CORS 使用 `*` 或本地地址、CORS 非 HTTPS、`EMBEDDING_PROVIDER=hash`、`EMBEDDING_LOCAL_FILES_ONLY=false`、未配置 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST`、关闭限流、关闭请求日志、`REQUEST_LOG_FORMAT` 不是 `text` 或 `json`、关闭 Agent Reviewer、关闭生成历史、历史库使用内存路径。

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
Copy-Item .env.example .env.runtime
```

然后编辑 `.env.runtime`，替换真实服务密钥、模型密钥和前端 HTTPS 域名。启动服务：

```powershell
docker compose up -d --build
docker compose ps
```

Docker 镜像默认安装 `requirements.txt` 中的统一后端依赖，适合 `EMBEDDING_PROVIDER=hash` 的本地验证和 Redis/RQ smoke test。生产或准生产如果使用 `EMBEDDING_PROVIDER=sentence_transformers`，需要在目标环境单独安装语义 embedding 依赖。建议使用 PyTorch CPU wheel index，避免默认 PyPI 解析 CUDA wheel：

```powershell
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu `
  "torch==2.12.1+cpu" "sentence-transformers>=5.6.0"
```

Linux shell 等价命令：

```bash
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu \
  'torch==2.12.1+cpu' 'sentence-transformers>=5.6.0'
```

Dockerfile 默认使用 `pip` 安装依赖，减少构建阶段的额外下载点。如果本机网络和缓存条件较好，也可以显式使用 `uv`：

```bash
INSTALLER=uv docker compose build
```

Redis/RQ smoke test 使用同一个 compose 文件和同一个镜像依赖入口。`docker-compose.yml` 默认把运行数据和模型缓存挂到 Docker named volume，避免 Linux 下宿主 `./data` 或模型缓存目录属主不匹配导致容器内 `appuser` 无法写入。需要独立 smoke 数据卷时，可以显式覆盖 volume 名称：

```bash
IMAGE_TAG=smoke APP_DATA_MOUNT=smoke-data MODEL_CACHE_MOUNT=smoke-model-cache docker compose build
IMAGE_TAG=smoke APP_DATA_MOUNT=smoke-data MODEL_CACHE_MOUNT=smoke-model-cache docker compose up -d
```

默认 compose 只发布 API 的宿主端口，不再把 Redis/MySQL 暴露到宿主机，避免和本机数据库端口冲突。compose 容器内部使用 `REDIS_URL=redis://redis:6379/0` 和 `DATABASE_URL=...@mysql:3306/...`；需要本机 Python 直连 Redis/MySQL 时，请使用单独的本机开发容器或临时 compose override 显式发布端口。

上述 smoke 命令会把 `/app/data` 和模型缓存目录挂到独立 Docker named volume。本次 Redis/RQ + MySQL worker smoke 使用 named volume 跑通；使用宿主 `./data`、`./.model_cache` bind mount 时，如果目录属主不匹配，容器会在运行目录检查阶段失败。

需要演练 Redis/MySQL 短暂不可用和恢复时，先确认 MySQL profile 服务已启动，再显式运行可选 smoke。该脚本会短暂停止 Redis/MySQL，验证队列检查能失败到明确错误，再恢复服务并验证检查重新通过；不要在共享生产环境直接运行：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d redis mysql
./.venv/bin/python scripts/smoke_runtime_dependency_outage.py --json
```

需要验证 Redis/RQ worker 在 MySQL profile 环境中连续执行测试计划 job 时，可以运行可选稳定性 smoke。该脚本会启动临时 worker 容器，提交多条 pytest adapter 执行 job，校验 job 全部进入终态、报告包含 passed/failed 混合结果，并确认每个 job 产生执行 artifact；脚本结束后会删除临时 worker。`DATABASE_BACKEND=mysql` 时，测试计划执行 job 状态也会写入 MySQL 的 `test_plan_execution_jobs` 表。

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d redis mysql
./.venv/bin/python scripts/smoke_rq_mysql_worker_stability.py --json
```

更长时长或并行 worker 演练可以显式指定轮次、每轮 job 数和 worker 数；每轮完成后脚本会检查测试计划执行队列 alert，确认无 active job、无 RQ failed registry 和无 MySQL/RQ 状态不一致：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d redis mysql
./.venv/bin/python scripts/smoke_rq_mysql_worker_stability.py --json --rounds 5 --jobs-per-round 6 --failure-count 2 --worker-count 2
```

需要验证需求到报告的测试 Agent workflow job 在 MySQL profile 环境中由 Redis/RQ worker 执行时，可以运行可选实机 smoke。该脚本会启动临时 worker 容器，提交 `TestAgentWorkflowRequest`，校验 workflow job、HTTP adapter、执行 artifact、`TestExecutionReport` 和 workflow 队列 alert；脚本结束后会删除临时 worker。`DATABASE_BACKEND=mysql` 时，workflow job 状态会写入 MySQL 持久化路径。

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d redis mysql
./.venv/bin/python scripts/smoke_test_agent_workflow_rq_mysql.py --json
```

更长时长或并行 worker 演练可以提高轮次、每轮 job 数和 worker 数；每轮完成后脚本会检查 workflow 队列 alert，确认无 active job、无 RQ failed registry 和无 MySQL/RQ 状态不一致。脚本会输出 `throughput`，可用 `--fail-over-max-queue-wait-ms` 和 `--fail-under-throughput-jobs-per-second` 增加吞吐门禁：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql-rq.yml --profile mysql up -d redis mysql
./.venv/bin/python scripts/smoke_test_agent_workflow_rq_mysql.py --json \
  --rounds 2 \
  --jobs-per-round 2 \
  --worker-count 2 \
  --fail-over-max-queue-wait-ms 60000 \
  --fail-under-throughput-jobs-per-second 0.001
```

需要把队列观测结果转成可告警阈值时，使用统一 queue alert 检查。它会聚合生成队列和测试计划执行队列的 snapshot，输出 `metrics` 和 `alerts`，并可按 active jobs、RQ queued/started/failed、worker heartbeat 和是否必须存在 worker 设置阈值：

```bash
./.venv/bin/python scripts/check_queue_alerts.py --json --require-worker --max-rq-failed 0 --max-worker-heartbeat-age-seconds 900
```

默认 worker heartbeat 阈值是 900 秒，用来避开 RQ 空闲 worker 维护间隔导致的误报。生产环境可基于 `collect_queue_alert_samples.py` 的采样结果和实际 worker heartbeat 行为再收紧。

服务还提供受 `X-API-Key` 保护的内部 metrics 接口：

```http
GET /api/v1/operations/metrics
GET /api/v1/operations/metrics/prometheus
```

Prometheus 抓取和告警规则模板见 [monitoring.md](monitoring.md)。规则模板位于 [monitoring/prometheus-alert-rules.yml](monitoring/prometheus-alert-rules.yml)，覆盖 readiness、LLM key 配置、业务阶段失败和耗时、job backlog、active job 长时间未清空、RQ failed registry 和无 worker 等基础告警。Prometheus/Alertmanager 的示例配置分别位于 [monitoring/prometheus-scrape-example.yml](monitoring/prometheus-scrape-example.yml) 和 [monitoring/alertmanager-route-example.yml](monitoring/alertmanager-route-example.yml)，可以作为内网接入演练的起点。

上线前可以先做离线监控验证，确认 Prometheus 文本输出和告警模板没有因为指标名漂移而断开：

```bash
./.venv/bin/python scripts/check_monitoring_metrics.py --json
```

依赖清单统一维护在 `requirements.txt`，不再按运行场景拆分多个入口。`constraints.txt` 提供关键依赖的上界约束，减少 CI 和镜像构建时跨大版本漂移；它不是完整 lock 文件，后续如果统一使用 `uv` 或 `pip-tools`，可以再生成严格锁定的依赖清单。

当前已验证的镜像构建路径：

- `requirements.txt` 统一后端镜像：包含 API、worker、RAG、MySQL backend、测试和 lint 依赖。
- 语义 embedding 依赖：不进入默认镜像；需要时按上面的 PyTorch CPU wheel 命令在目标环境单独安装。

不要使用宽松的 `torch>=...`，否则 Linux 构建可能从默认 PyPI 拉取 CUDA wheel，并额外解析 `nvidia-*`、`cuda-toolkit` 等大体积依赖。

`docker-compose.yml` 默认挂载 `app-data:/app/data` 和 `app-model-cache:/app/.model_cache/huggingface`，并通过 `/health` 做容器健康检查。Docker named volume 会避开常见的宿主目录 UID/GID 不匹配问题。

如果需要把运行文件直接暴露到宿主机，可以显式设置 `APP_DATA_MOUNT=./data` 和 `MODEL_CACHE_MOUNT=./.model_cache/huggingface`。Linux 部署时要确认这两个宿主目录对容器内 `appuser` 可写；如果目录由 `root` 创建且权限是 755，worker 会在运行目录检查阶段失败。

API 和 worker 容器启动时会先执行 `scripts/check_runtime_paths.py`，检查 `CHROMA_PATH`、`EMBEDDING_CACHE_DIR`，以及 SQLite backend 下 `GENERATION_HISTORY_DB_PATH` 的父目录是否可创建和写入。权限不正确时容器会直接退出，并在日志里输出具体目录。

可以先手动检查运行目录：

```bash
docker compose run --rm api python scripts/check_runtime_paths.py
```

启动后建议先跑内部 readiness 检查。它会验证生产配置、运行目录、数据库任务状态库和队列依赖；`GENERATION_JOB_QUEUE_BACKEND=rq` 时会检查 Redis 可达性，但不会调用真实 LLM：

```bash
docker compose exec api python scripts/check_readiness.py
```

启动后可以检查生成队列、worker 心跳和数据库任务状态：

```bash
docker compose exec api python scripts/check_generation_queue.py --fail-on-mismatch
```

测试计划执行队列检查会按 job function 过滤共享队列中的执行任务：

```bash
docker compose exec api python scripts/check_test_plan_execution_queue.py --fail-on-mismatch
```

还可以单独验证 worker 启动时依赖的 stale running 任务恢复逻辑。默认使用临时 SQLite 文件，不需要 Redis、真实 LLM 或 `TestClient`：

```bash
python scripts/smoke_recover_stale_generation_jobs.py
```

测试计划执行 worker smoke 会连续处理多个 in-memory job，并在启动时验证 stale running 恢复不会误杀 fresh job：

```bash
python scripts/smoke_test_plan_execution_worker.py
```

测试计划执行 runtime smoke 会验证 SQLite job 保留期清理、in-memory 队列满背压和 worker 多任务稳定性：

```bash
python scripts/smoke_test_plan_execution_runtime.py
```

MySQL 环境可以复用同一脚本连接当前业务库，脚本会验证完 fresh control job 后将其标记为失败，避免留下 active job：

```bash
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  python scripts/smoke_recover_stale_generation_jobs.py --backend mysql
```

如果需要机器可读输出：

```bash
docker compose exec api python scripts/check_readiness.py --json
docker compose exec api python scripts/check_generation_queue.py --json
docker compose exec api python scripts/check_test_plan_execution_queue.py --json
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
docker build -t ai-testcase-generator .
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

本机 Python 直连已发布宿主端口的 Docker MySQL 时，需要先安装可选依赖并初始化 schema：

```bash
uv pip install --python ./.venv/bin/python -r requirements.txt
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/init_mysql.py
```

Compose 运行 MySQL 时，复制 `.env.example` 为 `.env.runtime` 后需要设置 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`，并将数据库配置改为：

```env
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
MYSQL_CONNECT_TIMEOUT_SECONDS=10
MYSQL_READ_TIMEOUT_SECONDS=30
MYSQL_WRITE_TIMEOUT_SECONDS=30
```

然后使用 MySQL profile 启动：

```bash
docker compose --profile mysql up -d --build
```

`docker-compose.yml` 内置 `mysql` profile，会启动 `mysql:8.0`，挂载 `mysql-data` volume，并在新 volume 首次初始化时执行 `migrations/mysql/001_initial.sql`。该 profile 带有可解析的占位默认值；正式使用时应通过 shell 环境变量或 `.env.runtime` 覆盖 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD` 和 `DATABASE_URL`。如果 volume 已存在，MySQL 不会重新执行初始化脚本，也不会按新的 `MYSQL_*` 环境变量重置旧密码或旧数据。

已有 MySQL volume 或迁移脚本已执行过时，可以在 Compose 网络内重复运行初始化脚本；脚本会跳过 MySQL `1061 Duplicate key name` 这类已存在索引错误：

```bash
docker compose --profile mysql run --rm -T \
  -e DATABASE_BACKEND=mysql \
  -e DATABASE_URL='mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4' \
  api python scripts/init_mysql.py
```

MySQL backend 所需 `PyMySQL` 已纳入统一 `requirements.txt`。本机 Python 只有在 MySQL 显式发布宿主端口时才使用 `127.0.0.1:3306`，Compose 容器内部使用服务名 `mysql:3306`。应用会为 PyMySQL 设置连接、读、写超时，默认分别是 10/30/30 秒；也可以在 `DATABASE_URL` 中追加 `connect_timeout`、`read_timeout`、`write_timeout` 查询参数覆盖。初始化、备份、恢复、连接超时和恢复演练步骤见 [MySQL 初始化、备份与恢复](mysql-operations.md)。当前 MySQL backend 已通过本机 Docker MySQL store smoke、Redis/RQ worker smoke、完整 Compose API/worker 镜像 smoke、stale 恢复 smoke、5 任务稳定性 smoke、Redis/MySQL 短暂不可用演练脚本、RQ worker stability smoke、测试计划执行 job MySQL 持久化验证、测试 Agent workflow MySQL/RQ smoke、常驻 API/worker service-mode 对齐、12 job 多轮负载 smoke、2 worker 40 job 负载演练、Redis/MySQL 依赖抖动恢复演练和 service-mode 短窗口阈值采样；生产默认切换前仍建议做更长时长运行验证和高并发验证。

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

登录模块和订单退款模块可使用隔离 collection 做固定评估。Linux / WSL 登录示例：

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

订单退款模块使用 `CHROMA_PATH=data/chroma-refund-rag-eval`、`CHROMA_COLLECTION=refund_rag_eval_hash` 和 `tests/fixtures/refund_rag_eval_cases.json`。统一发布检查入口会同时执行登录和退款两个固定评估。

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
- `.\.venv\Scripts\python.exe -m mypy app/models/test_plan.py app/services/tool_adapters.py app/services/tool_artifacts.py app/services/tool_execution.py app/services/test_report.py app/services/test_plan_execution.py app/services/test_plan_execution_jobs.py app/services/test_plan_execution_store.py app/workers/test_plan_execution_rq.py` 必须通过，作为测试 Agent 契约模块的类型门禁。
- `/health` 可访问。
- `/ready` 或 `scripts/check_readiness.py` 必须返回 ready；如果使用 RQ，Redis 必须可达。
- 生产环境必须设置 `APP_ENV=production`，并确保启动配置校验通过。
- 所有 `/api/v1/*` 接口必须携带 `X-API-Key`。
- `CORS_ALLOW_ORIGINS` 必须配置为真实前端域名，不使用 `*`。
- 应用内 `RATE_LIMIT_*` 必须按真实调用量调整；公网环境仍建议在网关层做限流。
- 异步生成队列建议使用 `GENERATION_JOB_QUEUE_BACKEND=rq` 和 Redis/RQ；本机 Python 直连 Docker Redis 时使用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 内部使用 `REDIS_URL=redis://redis:6379/0`。
- 测试计划执行工具必须配置最小权限：`TEST_TOOL_HTTP_BASE_URL_ALLOWLIST` 限定目标服务，`TEST_TOOL_HTTP_ALLOWED_HEADERS` 限定可转发 header，pytest adapter 默认关闭；如需启用 pytest，必须配置最小 `TEST_TOOL_PYTEST_ALLOWED_PATHS` 和 `TEST_TOOL_PYTEST_ENV_ALLOWLIST`。
- 上线前运行 `scripts/check_generation_queue.py --fail-on-mismatch`，确认 RQ active registry 与数据库 `queued/running` 任务没有明显不一致。
- 上线前运行 `scripts/check_test_plan_execution_queue.py --fail-on-mismatch`，确认测试计划执行 job 的共享 RQ 队列与数据库 `queued/running` 任务没有明显不一致。
- 上线前运行 `scripts/smoke_recover_stale_generation_jobs.py`，确认过期 `running` 任务会被标记为 `generation_job_stale` 且新运行任务不会被误杀。
- 上线前运行 `scripts/smoke_test_plan_execution_worker.py`，确认测试计划执行 worker 能连续处理多个 job，并且 stale running 恢复不会误杀 fresh job。
- 上线前运行 `scripts/smoke_test_plan_execution_runtime.py`，确认测试计划执行 job 保留期清理、队列满背压和多任务 worker 路径仍然正常。
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
