# AI 测试用例生成助手

将自然语言需求、PRD 或历史用例知识库转换为结构化测试用例。服务使用 FastAPI 暴露接口，调用智谱大模型 JSON Mode，并通过 Chroma 检索企业知识约束输出。

项目理解文档见 [docs/project-guide.md](docs/project-guide.md)。
部署与 GitHub 发布说明见 [docs/deployment.md](docs/deployment.md)。

## 功能

- `POST /api/v1/test-cases/generate`：输入需求描述，返回结构化测试用例。
- `POST /api/v1/test-cases/export`：将测试用例导出为 Excel。
- `POST /api/v1/knowledge/ingest`：导入 PRD、历史用例等知识文本到 Chroma。
- `POST /api/v1/knowledge/query`：验证知识库检索结果。
- `GET /api/v1/knowledge/documents`：查看知识库文档清单和当前版本。
- `POST /api/v1/knowledge/documents/upsert`：按 `source` 更新或新增单个知识库文档。
- `DELETE /api/v1/knowledge/documents?source=...`：按 `source` 删除知识库文档。
- `GET /api/v1/generation-records`：查询生成历史记录。
- `GET /api/v1/generation-records/{record_id}`：查询单次生成详情。

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

## 启动

```powershell
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

也可以使用项目启动脚本：

```powershell
python scripts/run_server.py --host 127.0.0.1 --port 8000
```

后台启动并写入日志：

```powershell
scripts\start_server.cmd
```

打开接口文档：

```text
http://127.0.0.1:8000/docs
```

Docker 运行：

```powershell
docker build -t ai-testcase-generator .
docker run --rm -p 8000:8000 --env-file .env.runtime ai-testcase-generator
```

## 配置

优先读取系统环境变量：

```text
APP_API_KEY
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
RATE_LIMIT_ENABLED
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
REQUEST_LOG_ENABLED
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

生成接口默认会把请求、响应摘要、完整响应 JSON、失败原因和耗时写入 SQLite：`GENERATION_HISTORY_DB_PATH=data/app.sqlite3`。该数据库属于运行数据，已被 `.gitignore` 排除；部署时应挂载到持久化数据盘。

RAG 默认使用本地 `hash` embedding，便于无模型启动。需要切换到轻量中文语义模型时，可以配置：

```text
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_CACHE_DIR=.model_cache/huggingface
EMBEDDING_DEVICE=cpu
EMBEDDING_LOCAL_FILES_ONLY=true
```

不同 embedding 维度不能混用同一个 Chroma collection。切换模型时建议同步更换 `CHROMA_COLLECTION`，例如 `test_knowledge_bge_small_zh_v15`。

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

返回的历史摘要包含 `id`、`created_at`、`status`、`description`、`case_count`、`duration_ms`、`model`、`retrieved_sources` 等字段；详情接口会额外返回原始请求和生成响应。

## 集成方式

其他项目可以直接调用 REST API。生成接口返回稳定 JSON，导出接口返回 Excel 文件流；后续对接禅道、TestRail 或内部测试平台时，只需要在适配层把 `cases` 转换成目标平台字段。
