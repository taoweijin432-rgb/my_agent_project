# 本机运行基线

这份文档记录当前已验证通过的 Linux 本机运行方式：Redis 运行在 Docker，API 和 RQ worker 运行在本机 Python 虚拟环境。默认任务状态和生成历史写入本机 SQLite；也可以切换到 Docker MySQL，当前 MySQL backend 已完成本机 smoke。

## 1. 前提

- Docker 已启动。
- Redis 容器已运行并暴露到本机 `6379`。
- 如果要验证 MySQL backend，MySQL 容器需运行并暴露到本机 `3306`。
- Python 虚拟环境 `.venv` 已安装项目依赖。
- 当前目录为项目根目录。

确认 Redis 容器：

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Ports}} {{.Status}}'
```

如果没有 Redis 容器，可以启动一个本机开发用 Redis：

```bash
docker run -d --name agent-redis -p 6379:6379 redis:latest
```

确认 Python 依赖：

```bash
./.venv/bin/python -c "import fastapi, uvicorn, redis, rq, httpx; print('python deps ok')"
```

确认本机能连 Redis：

```bash
./.venv/bin/python -c "from redis import Redis; r=Redis.from_url('redis://127.0.0.1:6379/0'); print(r.ping())"
```

如果启用 MySQL，确认本机已安装可选依赖：

```bash
uv pip install --python ./.venv/bin/python -r requirements.txt
```

## 2. 配置

本机运行可以复用 `.env.runtime`，但必须覆盖 Redis 地址：

```bash
export REDIS_URL=redis://127.0.0.1:6379/0
```

原因：`.env.runtime` 中的 `REDIS_URL=redis://redis:6379/0` 是 Docker Compose 容器网络里的地址；本机 Python 进程应使用 `127.0.0.1`。

当前 smoke 配置建议：

```bash
APP_ENV=development
GENERATION_JOB_QUEUE_BACKEND=rq
REDIS_URL=redis://127.0.0.1:6379/0
RQ_QUEUE_NAME=generation-compose-smoke
EMBEDDING_PROVIDER=hash
AGENT_BUDGET_MAX_PROMPT_TOKENS=1
AGENT_WORKFLOW_BACKEND=langgraph
DATABASE_BACKEND=sqlite
GENERATION_HISTORY_DB_PATH=data/compose-smoke.sqlite3
RATE_LIMIT_ENABLED=false
REQUEST_LOG_ENABLED=false
```

`AGENT_BUDGET_MAX_PROMPT_TOKENS=1` 会让生成任务在预算门控处失败，避免 smoke test 调用真实 LLM。

可选 MySQL 配置：

```bash
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4
```

本机 Python 连接 Docker MySQL 时 host 使用 `127.0.0.1`；Docker Compose 容器内部连接 MySQL 时 host 应使用服务名 `mysql`。MySQL schema 可通过以下命令初始化：

```bash
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/init_mysql.py
```

## 3. 启动 API

在第一个终端执行：

```bash
set -a
. ./.env.runtime
set +a
export REDIS_URL=redis://127.0.0.1:6379/0
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

健康检查：

```bash
curl -sS http://127.0.0.1:8001/health
```

预期返回：

```json
{"status":"ok","service":"AI Test Case Generator"}
```

## 4. 启动 Worker

在第二个终端执行：

```bash
set -a
. ./.env.runtime
set +a
export REDIS_URL=redis://127.0.0.1:6379/0
./.venv/bin/python scripts/run_generation_worker.py
```

预期 worker 输出包含：

```text
Listening on generation-compose-smoke...
```

## 5. 提交异步任务

在第三个终端执行：

```bash
curl -sS -X POST http://127.0.0.1:8001/api/v1/test-cases/generation-jobs \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: compose-smoke-service-key-123456' \
  -d '{"description":"生成本机 Redis RQ 异步烟测用例","max_cases":3,"knowledge_top_k":0}'
```

返回中记录 `id`，然后查询任务：

```bash
curl -sS -H 'X-API-Key: compose-smoke-service-key-123456' \
  http://127.0.0.1:8001/api/v1/test-cases/generation-jobs/<job_id>
```

当前 smoke 配置下，预期最终状态是：

```text
status=failed
error.code=budget_exceeded
```

这表示 API 入队、Redis/RQ、worker 消费、预算门控和任务状态持久化都已跑通。

## 6. 检查队列和数据库

推荐用统一脚本检查队列、worker 和当前数据库 backend 的 `generation_jobs` 状态统计。

默认本机 SQLite + in-memory 队列检查：

```bash
./.venv/bin/python scripts/check_generation_queue.py
```

本机 Python 直连 Docker Redis/RQ 时：

```bash
GENERATION_JOB_QUEUE_BACKEND=rq \
REDIS_URL=redis://127.0.0.1:6379/0 \
RQ_QUEUE_NAME=generation-compose-smoke \
GENERATION_HISTORY_DB_PATH=data/compose-smoke.sqlite3 \
  ./.venv/bin/python scripts/check_generation_queue.py
```

如果使用 MySQL backend：

```bash
DATABASE_BACKEND=mysql \
GENERATION_JOB_QUEUE_BACKEND=rq \
REDIS_URL=redis://127.0.0.1:6379/0 \
RQ_QUEUE_NAME=generation-compose-smoke \
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/check_generation_queue.py --json --fail-on-mismatch
```

预期：

- `health.ok=true`，没有 `errors`。
- RQ `queued` 和 `started` 能与数据库 `queued/running` 大体对齐。
- `failed` registry 不应长期积压；如有 warning，需要结合 worker 日志排查。
- 如果要查看 `generation_records` 或 gate 审批状态，继续使用 API 列表接口或 MySQL/SQLite 查询。

## 7. 停止服务

在 API 和 worker 终端按 `Ctrl+C`。

Redis 容器可以继续保留给下次开发使用；如需停止：

```bash
docker stop agent-redis
```

## 8. 当前结论

本机开发/演示运行方式已经验证通过。Docker Compose 轻量 Redis/RQ smoke、MySQL store smoke 和 Redis/RQ + MySQL worker smoke 已验证通过；完整 ML/RAG 镜像构建仍受 `chromadb`、`numpy`、`onnxruntime` 等依赖下载影响，应在网络稳定环境单独验证。

smoke 验证复用统一 `docker-compose.yml`，通过环境变量把运行数据切到 Docker named volume；依赖仍统一来自 `requirements.txt`。

```bash
IMAGE_TAG=smoke APP_DATA_MOUNT=smoke-data MODEL_CACHE_MOUNT=smoke-model-cache docker compose build
REDIS_HOST_PORT=6380 IMAGE_TAG=smoke APP_DATA_MOUNT=smoke-data MODEL_CACHE_MOUNT=smoke-model-cache docker compose up -d
```

当前已验证的 smoke 预期结果：异步任务最终 `status=failed` 且 `error.code=budget_exceeded`，RQ 队列长度为 `0`，当前数据库 backend 中有对应 `generation_jobs` 和 `generation_records` 记录。`scripts/check_generation_queue.py` 可用于查看队列 registry、worker 心跳和业务表状态统计。默认 backend 仍是 SQLite；切到 MySQL 前需要先安装可选依赖并初始化 schema。
