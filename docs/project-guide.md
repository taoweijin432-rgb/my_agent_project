# AI 测试用例生成助手项目理解文档

## 1. 项目定位

这个项目是一个可以被其他系统调用的 AI 测试用例生成服务。

它的核心目标是：

- 输入一段自然语言需求、功能说明或 PRD 内容。
- 结合企业知识库中的 PRD、历史测试用例、测试规范等资料。
- 调用智谱大模型生成结构化测试用例。
- 用 Pydantic 校验输出格式。
- 最终通过 API 返回 JSON，或导出为 Excel。

可以把它理解成一个后端服务，不是聊天机器人页面。其他项目可以通过 HTTP API 调用它。

## 2. 一句话流程

用户输入需求描述 -> Chroma 检索相关知识 -> 构造 Prompt -> 调用智谱 LLM JSON Mode -> Pydantic 校验 -> 返回测试用例 JSON 或 Excel。

## 3. 核心能力

项目目前包含这些能力：

- FastAPI 提供 RESTful 接口。
- 智谱大模型生成测试用例。
- Chroma 向量数据库存储和检索企业知识。
- Prompt 强制覆盖正常流程、等价类、边界值、异常流、权限校验。
- LLM 输出必须是 JSON object。
- Pydantic 校验测试用例字段和类型。
- 格式错误时自动重试。
- 支持 Excel 导出。
- 支持其他项目通过 API 集成。

## 4. 项目目录说明

```text
app/
  main.py                 FastAPI 应用入口
  api/
    routes.py             所有 HTTP API 路由
  core/
    config.py             配置读取，包括 API Key、模型名、Chroma 路径
  models/
    test_case.py          Pydantic 数据模型和字段校验
  services/
    llm.py                智谱大模型调用封装
    prompt.py             Prompt 模板和 Few-shot 示例
    rag.py                Chroma RAG 检索和文档导入
    generator.py          测试用例生成主流程
    excel_exporter.py     Excel 导出

scripts/
  ingest_documents.py     命令行导入知识库文档
  run_server.py           服务启动脚本

tests/
  test_models.py          数据模型校验测试

requirements.txt          Python 依赖
README.md                 使用说明
```

## 5. 主要 API

### 5.1 健康检查

```http
GET /health
```

用于确认服务是否启动成功。

返回示例：

```json
{
  "status": "ok",
  "service": "AI Test Case Generator"
}
```

### 5.2 生成测试用例

```http
POST /api/v1/test-cases/generate
```

请求示例：

```json
{
  "description": "用户可以使用手机号和验证码登录系统。验证码 6 位数字，5 分钟有效，错误 5 次后锁定 10 分钟。",
  "max_cases": 8,
  "knowledge_top_k": 5,
  "include_context": false
}
```

字段说明：

- `description`：需求描述，必填。
- `max_cases`：最多生成多少条测试用例。
- `knowledge_top_k`：从 Chroma 知识库中检索多少条上下文。
- `include_context`：是否在响应里返回检索到的知识库片段，调试时可以设为 `true`。
- `focus_types`：可选，指定重点生成哪些用例类型。

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
    "retrieved_chunks": 3
  },
  "retrieved_context": []
}
```

### 5.3 导出 Excel

```http
POST /api/v1/test-cases/export
```

输入一组测试用例，返回 Excel 文件流。

### 5.4 导入知识库

```http
POST /api/v1/knowledge/ingest
```

请求示例：

```json
{
  "documents": [
    {
      "source": "prd-login.md",
      "content": "手机号验证码登录，验证码 6 位数字，5 分钟有效。"
    }
  ],
  "chunk_size": 900
}
```

作用是把 PRD、历史用例、测试规范等文本切分后写入 Chroma。

### 5.5 查询知识库

```http
POST /api/v1/knowledge/query
```

用于调试 RAG 检索效果。

请求示例：

```json
{
  "query": "验证码登录边界值",
  "top_k": 5
}
```

## 6. 测试用例数据结构

每条测试用例固定包含：

```json
{
  "id": "TC-001",
  "title": "用例标题",
  "precondition": "前置条件",
  "steps": ["操作步骤 1", "操作步骤 2"],
  "expected": ["预期结果 1", "预期结果 2"],
  "type": "functional"
}
```

`type` 允许的值：

- `functional`：正常功能流程。
- `boundary`：边界值。
- `exception`：异常流。
- `permission`：权限校验。
- `compatibility`：兼容性。
- `performance`：性能。
- `security`：安全。

如果大模型输出中文类型，例如 `边界值`、`异常流`、`权限校验`，后端会尽量转换成标准英文枚举。

## 7. 生成链路详解

生成接口的核心代码在 `app/services/generator.py`。

完整链路如下：

1. API 层接收 `GenerateRequest`。
2. `RagService.search()` 根据需求描述从 Chroma 检索相关知识。
3. `build_generation_messages()` 把需求、知识库上下文、Few-shot 示例拼成 Prompt。
4. `LLMClient.generate_json()` 调用智谱 `/chat/completions` 接口。
5. 智谱返回 JSON 字符串。
6. 后端解析 JSON。
7. `TestCaseCollection.model_validate()` 用 Pydantic 校验字段。
8. 如果校验失败，把错误信息放回 Prompt 自动重试。
9. 校验成功后返回 `GenerateResponse`。

## 8. RAG 是怎么工作的

RAG 相关代码在 `app/services/rag.py`。

目前流程：

- 文档导入时，把长文本按 `chunk_size` 切分成片段。
- 每个片段写入 Chroma。
- 生成测试用例时，用用户需求作为查询文本。
- Chroma 返回最相关的知识片段。
- 这些片段会进入 Prompt，约束大模型不要凭空编造业务规则。

embedding 支持配置化。默认使用本地 deterministic hash embedding，不需要额外下载模型，适合本地启动和演示；也可以切换为 `sentence_transformers`，例如轻量中文模型 `BAAI/bge-small-zh-v1.5`。切换不同 embedding 模型时，需要使用新的 Chroma collection，避免旧向量维度和新模型维度不一致。

## 9. Prompt 约束策略

Prompt 相关代码在 `app/services/prompt.py`。

当前 Prompt 做了几件事：

- 要求只输出 JSON object。
- 顶层字段必须是 `cases`。
- 每条用例必须包含固定字段。
- `steps` 和 `expected` 必须是字符串数组。
- `type` 必须使用标准枚举。
- 明确要求覆盖正常流程、等价类、边界值、异常流、权限校验。
- 提供登录场景 Few-shot 示例，帮助模型稳定输出格式。

## 10. 配置读取

配置代码在 `app/core/config.py`。

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

项目也兼容读取当前已有的 `.env/config.py`。

注意：`.env/config.py` 里如果有真实 API Key 或服务调用密钥，不要提交到版本库。除 `/health` 外，业务接口需要在请求头携带 `X-API-Key`。服务会为响应增加 `X-Request-ID` 和 `X-Process-Time-ms`，并默认对 `/api/v1/*` 做内存级限流。生成接口还会默认把生成请求、响应、失败原因和耗时写入 `GENERATION_HISTORY_DB_PATH` 指向的 SQLite 数据库。

## 11. 如何启动

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动服务：

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py --host 127.0.0.1 --port 8000
```

访问接口文档：

```text
http://127.0.0.1:8000/docs
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 12. 如何导入企业知识

方式一：通过 API 导入。

```http
POST /api/v1/knowledge/ingest
```

方式二：通过脚本导入本地文件。

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py docs/prd-login.md docs/history-cases.md
```

适合导入的内容：

- PRD。
- 用户故事。
- 接口文档。
- 历史测试用例。
- 缺陷复盘。
- 测试设计规范。
- 业务规则说明。

## 13. 如何接入其他项目

其他项目只需要调用 HTTP API。

最常见集成方式：

- 测试平台传入需求描述，调用生成接口。
- 服务返回 `cases`。
- 测试平台把 `cases` 映射成自己的用例字段。
- 如果需要 Excel，调用导出接口。

推荐集成边界：

- 这个服务负责 AI 生成、RAG、格式校验。
- 外部平台负责用户界面、权限、项目管理、用例审批和落库。

## 14. 后续扩展点

可以优先扩展这些方向：

- 替换更强的 embedding 模型，提高 RAG 召回质量。
- 增加文件上传接口，支持上传 PRD、Word、PDF。
- 增加测试管理平台 adapter，例如禅道、TestRail、飞书多维表格。
- 增加异步任务，适合长需求文档批量生成。
- 增加用例质量评分，例如覆盖率、重复率、风险等级。
- 增加用户可配置的测试策略模板。
- 增加接口鉴权，避免服务被未授权调用。

## 15. 常见问题

### 15.1 没有生成结果

先检查：

- `ZHIPU_API_KEY` 是否配置。
- 智谱接口是否可访问。
- 模型名是否正确。
- 日志里是否有 401、403、429 或超时。

### 15.2 输出格式不对

项目已经做了 JSON Mode 和 Pydantic 校验。如果仍然失败：

- 降低模型温度。
- 增强 Prompt 中的 Schema 示例。
- 增加更多 Few-shot。
- 提高 `LLM_MAX_RETRIES`。

### 15.3 RAG 检索效果差

可以检查：

- 是否已导入知识库。
- `knowledge_top_k` 是否太小。
- 文档切分是否太碎或太长。
- 当前 hash embedding 只是本地简化方案，生产建议替换为专业 embedding。

## 16. 当前项目状态

当前版本是一个可运行的后端基础版，已经具备主流程：

- API 输入需求。
- RAG 检索。
- LLM 生成。
- Schema 校验。
- JSON 返回。
- Excel 导出。

它适合作为第一个可集成版本。后续重点不是重写架构，而是增强知识库质量、模型稳定性、平台集成和权限安全。
