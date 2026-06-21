# 部署与 GitHub 发布说明

这份文档用于把项目整理到可部署、可放入 GitHub 仓库的最低标准。当前项目适合做内网服务、个人项目集成或受控测试环境，不建议直接裸露到公网。

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
AGENT_QUERY_REWRITE_ENABLED=true
AGENT_QUERY_REWRITE_MIN_CHUNKS=1
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
REQUEST_LOG_ENABLED=true
GENERATION_HISTORY_ENABLED=true
GENERATION_HISTORY_DB_PATH=data/app.sqlite3
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
CORS_ALLOW_CREDENTIALS=false
```

本地仍兼容读取 `.env/config.py`，但这个目录已经被 `.gitignore` 排除，不应提交。

当 `APP_ENV=production` 时，服务会在启动阶段强制校验生产配置。以下情况会直接拒绝启动：缺少真实 `APP_API_KEY` 或 `ZHIPU_API_KEY`、CORS 使用 `*` 或本地地址、CORS 非 HTTPS、`EMBEDDING_PROVIDER=hash`、`EMBEDDING_LOCAL_FILES_ONLY=false`、关闭限流、关闭请求日志、关闭 Agent Reviewer、关闭生成历史、历史库使用内存路径。

## 2. 本地运行

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

`docker-compose.yml` 会挂载 `./data:/app/data` 和 `./.model_cache/huggingface:/app/.model_cache/huggingface`，并通过 `/health` 做容器健康检查。

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

生成历史默认写入 `data/app.sqlite3`。如果使用 Docker，必须挂载 `/app/data` 或单独挂载 SQLite 文件所在目录，否则容器删除后历史记录会丢失。

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

## 5. GitHub 发布检查

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
- `AGENT_REVIEW_ENABLED` 必须保持开启；是否启用 `AGENT_REVIEW_RETRY_ENABLED` 取决于成本预算和质量门槛。
- `GENERATION_HISTORY_DB_PATH` 所在目录必须持久化，并纳入备份策略。
- `APP_API_KEY` 和 `ZHIPU_API_KEY` 必须来自环境变量或部署密钥管理。
- Chroma 数据目录需要持久化备份。
- 模型缓存目录需要放在 D 盘或部署机器的数据盘，避免写入系统盘。
- 对外暴露前应增加网关限流、访问日志、错误监控和 HTTPS。
