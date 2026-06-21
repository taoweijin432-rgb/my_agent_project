# 部署与 GitHub 发布说明

这份文档用于把项目整理到可部署、可放入 GitHub 仓库的最低标准。当前项目适合做内网服务、个人项目集成或受控测试环境，不建议直接裸露到公网。

## 1. 必要配置

生产或准生产环境必须通过环境变量提供配置，不要把真实 key 写入仓库。

```text
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
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
REQUEST_LOG_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
CORS_ALLOW_CREDENTIALS=false
```

本地仍兼容读取 `.env/config.py`，但这个目录已经被 `.gitignore` 排除，不应提交。

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

构建镜像：

```powershell
docker build -t ai-testcase-generator .
```

运行镜像：

```powershell
docker run --rm -p 8000:8000 `
  --env-file .env.runtime `
  -v ${PWD}\data\chroma:/app/data/chroma `
  -v ${PWD}\.model_cache\huggingface:/app/.model_cache/huggingface `
  ai-testcase-generator
```

`.env.runtime` 只放在本机，不提交到仓库。容器镜像不会包含 `.env/`、`.model_cache/`、`data/chroma/`、`logs/` 或 `knowledge_export/`。

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
- 所有 `/api/v1/*` 接口必须携带 `X-API-Key`。
- `CORS_ALLOW_ORIGINS` 必须配置为真实前端域名，不使用 `*`。
- 应用内 `RATE_LIMIT_*` 必须按真实调用量调整；公网环境仍建议在网关层做限流。
- `APP_API_KEY` 和 `ZHIPU_API_KEY` 必须来自环境变量或部署密钥管理。
- Chroma 数据目录需要持久化备份。
- 模型缓存目录需要放在 D 盘或部署机器的数据盘，避免写入系统盘。
- 对外暴露前应增加网关限流、访问日志、错误监控和 HTTPS。
