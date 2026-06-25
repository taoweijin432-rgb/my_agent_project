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

用户输入需求描述 -> 工作流状态初始化 -> 需求分析 -> Chroma 检索相关知识 -> 召回不足时 query rewrite 并再检索 -> 测试策略规划 -> 构造 Prompt -> 成本预算门控 -> 调用智谱 LLM JSON Mode -> Pydantic 校验 -> 后处理 -> Reviewer 审查、质量门控和条件重试 -> usage 估算和历史记录 -> 返回测试用例 JSON 或 Excel。

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
    agent_workflow.py     Agent 工作流状态、节点抽象和测试策略规划
    query_rewrite.py      RAG 召回不足时的本地查询改写
    reviewer.py           Reviewer 节点的本地质量审查和重试反馈
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

### 5.2.1 异步生成测试用例

```http
POST /api/v1/test-cases/generation-jobs
GET /api/v1/test-cases/generation-jobs
GET /api/v1/test-cases/generation-jobs/{job_id}
```

异步入口适合长需求文档、批量生成或前端不希望长时间等待 HTTP 响应的场景。提交接口返回 202 和任务详情，任务初始状态通常是 `queued`；后台 worker 会复用同步生成链路，继续执行 RAG、LLM 调用、Reviewer、门控和历史落库。

任务状态包括：

- `queued`：已接单，等待 worker。
- `running`：正在生成。
- `succeeded`：生成完成，详情里包含 `response`。
- `failed`：生成失败，详情里包含 `error`；如果是预算或质量门控失败，`error.gate` 会包含 human-in-the-loop 结构化信息。

队列配置由 `GENERATION_JOB_QUEUE_BACKEND`、`GENERATION_JOB_MAX_QUEUE_SIZE`、`GENERATION_JOB_RETENTION_SECONDS`、`GENERATION_JOB_STALE_AFTER_SECONDS`、`REDIS_URL` 和 `RQ_QUEUE_NAME` 控制。默认 `in_memory` backend 适合本地开发；`rq` backend 使用 Redis/RQ 派发任务，并把任务状态写入当前 `DATABASE_BACKEND` 对应的数据库。worker 启动时会把超过 stale 阈值仍处于 `running` 的任务标记为失败。默认 SQLite 状态库适合单机部署；MySQL backend 已实现并通过本机 Docker smoke、备份恢复、Compose 模板和 5 任务稳定性 smoke，多实例生产还需要补故障恢复、队列可观测性和更长时长运行验证。

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

### 5.6 管理知识库文档

```http
GET /api/v1/knowledge/documents
POST /api/v1/knowledge/documents/upsert
DELETE /api/v1/knowledge/documents?source=knowledge/prd/login.md
```

文档管理接口用于查看当前索引里的文档清单、按 `source` 更新单个文档、按 `source` 删除文档。upsert 会替换同 `source` 的旧 chunk，并把当前文档版本号加 1。

### 5.7 查询和处理门控记录

```http
GET /api/v1/generation-gates?status=pending
GET /api/v1/generation-gates?status=approved
GET /api/v1/generation-gates?status=rejected
GET /api/v1/generation-gates?status=all
POST /api/v1/generation-gates/{record_id}/resolve
```

门控列表只返回预算门控或质量门控触发的失败记录。默认 `status=pending`，适合构建待人工确认、人工复核或审批列表；`status=all` 可用于审计。

处理门控记录时，请求体示例：

```json
{
  "decision": "approved",
  "resolved_by": "qa-owner",
  "comment": "允许继续处理"
}
```

`decision` 只能是 `approved` 或 `rejected`。已经处理过的门控记录不会再次覆盖，重复处理会返回 409。

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

生成接口的核心代码在 `app/services/generator.py`，工作流节点和策略规划在 `app/services/agent_workflow.py`。Agent 架构说明见 [docs/agent-architecture.md](agent-architecture.md)。

完整链路如下：

1. API 层接收 `GenerateRequest`。
2. `analyze_requirement()` 做本地需求分析和风险类型识别。
3. `RagService.search()` 根据需求描述从 Chroma 检索相关知识。
4. `route_after_retrieval` 判断召回是否足够。
5. 如果召回不足，`rewrite_query` 扩展检索 query，并通过 `retrieve_rewritten_knowledge` 再检索一次。
6. `plan_test_generation()` 基于需求分析和知识来源规划测试策略。
7. `build_generation_messages()` 把需求、知识库上下文、测试策略、Few-shot 示例拼成 Prompt。
8. `check_budget` 在调用 LLM 前估算 prompt token 和费用，超限时返回 409。
9. `LLMClient.generate_json()` 调用智谱 `/chat/completions` 接口。
10. 后端解析 JSON。
11. `TestCaseCollection.model_validate()` 用 Pydantic 校验字段。
12. 如果校验失败，把错误信息放回 Prompt 自动重试。
13. 校验成功后后处理用例。
14. `review_cases` 复用本地质量评分做 Reviewer 审查。
15. `route_after_review` 根据配置决定接受结果，或把覆盖修复反馈写入下一轮 Prompt。
16. 如果 `AGENT_REVIEW_REQUIRE_PASS=true`，`check_quality_gate` 会阻断 Reviewer 未通过的结果。
17. 估算 usage，并返回 `GenerateResponse`。

每次生成都会创建一个 `GenerationWorkflowState` 作为短期记忆。工作流节点通过这个 state 读写需求分析、RAG 上下文、重写后的检索 query、测试策略、Prompt、LLM payload、校验结果、Reviewer 结论和 usage。每次成功生成都会在 `metadata.workflow_steps` 中返回节点轨迹，包括节点名、状态、摘要、耗时、实际 backend 和结构化 `trace`。`trace` 会记录路由决策、RAG 召回数、预算估算、Reviewer 分数、缺失验收点、覆盖修复原因和 usage 等机器可读字段。

query rewrite 是本地确定性逻辑，不调用 LLM。默认 `AGENT_QUERY_REWRITE_ENABLED=true`，当初次召回少于 `AGENT_QUERY_REWRITE_MIN_CHUNKS` 时触发一次重检索。

Reviewer 默认只记录审查结论，不增加 LLM 调用。显式开启 `AGENT_REVIEW_RETRY_ENABLED=true` 后，如果审查分数低于 `AGENT_REVIEW_MIN_SCORE` 或存在阻断性告警，且还有 `LLM_MAX_RETRIES` 预算，系统会把 Reviewer 反馈注入下一轮 Prompt。若缺失目标类型或关键验收点，反馈会进入覆盖修复模式，要求补齐缺口；如果生成数量已满，则要求替换低价值、重复或泛化用例，而不是超出 `max_cases` 追加。

预算门控默认不阻断。设置 `AGENT_BUDGET_MAX_PROMPT_TOKENS` 或 `AGENT_BUDGET_MAX_ESTIMATED_COST` 后，超限请求会在调用 LLM 前返回 409，并把估算 usage 写入失败历史。质量门控默认不阻断；设置 `AGENT_REVIEW_REQUIRE_PASS=true` 后，Reviewer 未通过的结果会返回 409，交给人工确认或调整需求后重试。对真实评估或接近生产的运行，建议同时设置 `AGENT_REVIEW_RETRY_ENABLED=true` 和 `AGENT_REVIEW_REQUIRE_PASS=true`，避免 Reviewer 已识别缺口时仍返回成功响应。

门控失败时，API 返回结构化 `detail`，字段包括：

```json
{
  "code": "budget_exceeded",
  "gate": "budget",
  "message": "Generation requires human confirmation: ...",
  "action_required": "human_confirmation",
  "usage": {},
  "review": null
}
```

质量门控失败时 `code=quality_gate_failed`、`gate=quality`，并会在 `review` 中返回 Reviewer 审查结论。调用方可以据此进入人工确认、人工复核或调整输入后重试。

门控失败记录会持久化到生成历史中，并可通过 `GET /api/v1/generation-gates` 单独查询。历史摘要和详情都会返回 `gate` 字段。

生成记录落库后，历史详情会基于请求和响应计算一份本地质量报告。评分维度包括用例数量、标题重复率、目标类型覆盖、步骤/预期完整度、知识库 grounding 和关键验收点覆盖。关键验收点会从用户需求和已召回的 RAG 片段中提取，缺失项会进入 `missing_acceptance_keywords` 和 `warnings`，用于 Reviewer retry、质量门控、历史回放和人工复核。该评分不会调用大模型，也不替代人工验收。

生成 metadata 和历史记录还包含 `usage`。当前 usage 通过字符数启发式估算 token，用于成本趋势和滥用排查；如果配置每千 token 单价，会额外返回估算费用。该值不等同于模型供应商账单。

## 8. RAG 是怎么工作的

RAG 相关代码在 `app/services/rag.py`。

目前流程：

- 文档导入时，把长文本按 `chunk_size` 切分成片段。
- 每个片段写入 Chroma。
- 每个片段的 metadata 会记录 `source`、`document_type`、`module`、`tags`、`version`、`content_hash` 和 `updated_at`。
- 生成测试用例时，用用户需求作为查询文本。
- Chroma 返回最相关的知识片段。
- 这些片段会进入 Prompt，约束大模型不要凭空编造业务规则。

embedding 支持配置化。默认使用本地 deterministic hash embedding，不需要额外下载模型，适合本地启动和演示；也可以切换为 `sentence_transformers`，例如轻量中文模型 `BAAI/bge-small-zh-v1.5`。切换不同 embedding 模型时，需要使用新的 Chroma collection，避免旧向量维度和新模型维度不一致。

批量初始化知识库时可以继续使用导入脚本配合 `--reset`。日常维护单个文档时优先使用 upsert/delete 接口，避免同一个 `source` 的旧内容残留在检索结果中。

当前阶段不需要为了登录验证大范围重写知识库。已经导入并能召回的 PRD 可以继续作为真实链路验证材料；如果生成结果遗漏了已召回文档里的规则，优先检查 Prompt、Reviewer 和质量门控是否覆盖，而不是先怀疑知识库不存在。

需要更新知识库的典型情况：

- RAG query 没有命中目标 `source`，或 `retrieved_chunks=0`。
- 检索片段命中旧版本 PRD、旧接口字段或已废弃规则。
- 文档没有明确验收口径，例如状态、阈值、有效期、权限矩阵、安全防护、审计字段只写成泛泛描述。
- 同一个功能的 PRD、接口、安全要求分散在多个文件，导致 top_k 容易召回不完整。

后续推荐把知识库整理为 PRD、接口契约、权限矩阵、安全要求、审计日志和历史缺陷/测试用例等分层文档。每个文档保持稳定 `source`，使用 upsert 更新；每次更新后先调用知识库查询接口确认目标规则能被召回，再跑生成链路。

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

项目也兼容读取当前已有的 `.env/config.py`。

注意：`.env/config.py` 里如果有真实 API Key 或服务调用密钥，不要提交到版本库。除 `/health` 外，业务接口需要在请求头携带 `X-API-Key`。服务会为响应增加 `X-Request-ID` 和 `X-Process-Time-ms`，并默认对 `/api/v1/*` 做内存级限流。生成接口默认把生成请求、响应、失败原因和耗时写入 `DATABASE_BACKEND=sqlite`、`GENERATION_HISTORY_DB_PATH` 指向的 SQLite 数据库；`DATABASE_BACKEND=mysql` 代码路径已实现并通过本机 Docker MySQL smoke，启用前需要安装 `requirements-mysql.txt` 并初始化 schema。异步生成可使用进程内 worker 或 Redis/RQ 外部队列；直接在 WSL/本机 Python 运行时可用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 内部使用 `REDIS_URL=redis://redis:6379/0`。`AGENT_WORKFLOW_BACKEND` 默认使用 `langgraph`；`local` backend 保留为 fallback 和行为对照。Reviewer 默认开启并写入 `metadata.review`；自动重试默认关闭，避免隐式增加 LLM 成本。

生产环境应设置 `APP_ENV=production`。此时应用会在启动时强制校验关键配置，包括真实服务密钥、真实模型密钥、HTTPS CORS 来源、语义 embedding、限流、请求日志、Agent Reviewer 和持久化历史库路径；校验失败会拒绝启动。

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
- 补齐 MySQL 生产化：Compose 服务模板、备份恢复、连接池参数、稳定性验证和默认 backend 切换评估。
- 增强 Redis/RQ 队列治理，例如原子背压、队列指标、失败率统计和 worker 运行时长监控。
- 增强用例质量评分，例如覆盖率、风险等级和人工验收结果回流。
- 增加用户可配置的测试策略模板。
- 增加用户体系和项目级权限隔离。

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
- 是否使用了和当前 embedding 维度匹配的 Chroma collection。
- 目标规则是否实际存在于召回片段中，可以临时设置 `include_context=true` 查看。
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
