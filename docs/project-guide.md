# AI 测试用例生成助手项目理解文档

## 1. 项目定位

这个项目是一个可以被其他系统调用的 AI 测试用例生成服务。

它的核心目标是：

- 输入一段自然语言需求、功能说明或 PRD 内容。
- 结合企业知识库中的 PRD、历史测试用例、测试规范等资料。
- 调用智谱大模型生成结构化测试用例。
- 用 Pydantic 校验输出格式。
- 最终通过 API 返回 JSON，导出为 Excel 或 pytest 自动化模板。
- 对生成用例和 PRD 验收点做覆盖率评估，辅助发现遗漏。

可以把它理解成一个可被其他系统集成的后端服务。仓库同时提供 React + Vite 前端工作台，用于本地操作、演示和验证主要流程；正式生产中的用户、项目、权限和用例管理仍建议由外部测试平台或后续生产级后台承接。

## 2. 一句话流程

用户输入需求描述 -> 工作流状态初始化 -> 需求分析 -> Chroma 检索相关知识 -> 召回不足时 query rewrite 并再检索 -> 测试策略规划 -> 构造 Prompt -> 成本预算门控 -> 调用智谱 LLM JSON Mode -> Pydantic 校验 -> 后处理 -> Reviewer 审查、质量门控和条件重试 -> usage 估算和历史记录 -> 返回测试用例 JSON、Excel、pytest 模板或覆盖率评估报告。

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
- 支持 pytest 自动化模板导出。
- 支持需求点到测试用例的覆盖率评估。
- 提供 React + Vite 前端工作台，覆盖生成、任务、测试计划、执行报告、知识库、历史、门控和覆盖率评估入口。
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
    coverage.py           需求覆盖率评估
    excel_exporter.py     Excel 导出
    pytest_exporter.py    pytest 模板导出

frontend/
  src/App.tsx             前端工作台页面组合和状态编排
  src/api/client.ts       API client 和 URL、query、错误归一化工具
  src/api/download.ts     Blob 下载工具
  src/api/settings.ts     API Base 和 API Key 持久化
  src/api/types.ts        后端 DTO TypeScript 类型

scripts/
  ingest_documents.py     命令行导入知识库文档
  run_server.py           服务启动脚本
  compare_generation_efficiency.py 生成效率和覆盖率对比脚本

tests/
  test_models.py          数据模型校验测试

requirements.txt          统一后端依赖入口，包含运行、测试、lint 和类型检查依赖
constraints.txt           关键依赖版本约束
README.md                 项目入口和快速启动
docs/README.md            正式文档总览
```

## 5. 主要 API

### 5.1 健康检查

```http
GET /health
GET /ready
```

`/health` 用于确认服务进程是否启动成功；`/ready` 用于内部 readiness 检查，会验证生产配置、运行目录可写性、数据库任务状态库、队列依赖和 LLM key 配置。`/ready` 不调用真实 LLM，检查失败时 HTTP 状态码为 503。

`/health` 返回示例：

```json
{
  "status": "ok",
  "service": "AI Test Case Generator"
}
```

`/ready` 返回示例：

```json
{
  "ready": true,
  "status": "ready",
  "service": "AI Test Case Generator",
  "environment": "development",
  "checks": []
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

异步入口适合长需求内容、批量生成或前端不希望长时间等待 HTTP 响应的场景。提交接口返回 202 和任务详情，任务初始状态通常是 `queued`；后台 worker 会复用同步生成链路，继续执行 RAG、LLM 调用、Reviewer、门控和历史落库。

任务状态包括：

- `queued`：已接单，等待 worker。
- `running`：正在生成。
- `succeeded`：生成完成，详情里包含 `response`。
- `failed`：生成失败，详情里包含 `error`；如果是预算或质量门控失败，`error.gate` 会包含 human-in-the-loop 结构化信息。

队列配置由 `GENERATION_JOB_QUEUE_BACKEND`、`GENERATION_JOB_MAX_QUEUE_SIZE`、`GENERATION_JOB_RETENTION_SECONDS`、`GENERATION_JOB_STALE_AFTER_SECONDS`、`REDIS_URL` 和 `RQ_QUEUE_NAME` 控制。默认 `in_memory` backend 适合本地开发；`rq` backend 使用 Redis/RQ 派发任务，并把任务状态写入当前 `DATABASE_BACKEND` 对应的数据库。worker 启动时会把超过 stale 阈值仍处于 `running` 的任务标记为失败。默认 SQLite 状态库适合单机部署；MySQL backend 已实现并通过本机 Docker smoke、备份恢复、Compose 模板、stale 恢复 smoke、5 任务稳定性 smoke、Redis/MySQL 短暂不可用演练脚本、RQ worker stability smoke、queue alert 阈值检查和测试计划执行 job MySQL 持久化验证；多实例生产还需要补更长时长运行验证。测试计划执行链路还新增了 `scripts/check_test_plan_execution_queue.py` 和 `scripts/smoke_test_plan_execution_worker.py`，前者按 job function 过滤共享 RQ 队列中的测试计划执行任务，后者验证进程内 worker 连续处理多个执行 job 的稳定性。需求到报告的测试 Agent workflow job 也复用这套队列和数据库配置，用于把真实 LLM 计划生成从同步 HTTP 请求中移出。

### 5.3 导出 Excel

```http
POST /api/v1/test-cases/export
```

输入一组测试用例，返回 Excel 文件流。

### 5.4 导出 pytest

```http
POST /api/v1/test-cases/export/pytest
```

输入一组测试用例，返回 Python 文件流。默认 `adapter=template`，导出的模板默认 `skip_by_default=true`，其中 `execute_case()` 需要测试人员补充真实 API 或 UI 自动化操作。

如果设置 `adapter=login_api`，会导出一个可执行的登录 API pytest adapter 示例。该 adapter 使用 Python 标准库 `urllib.request` 调用登录接口，读取 `LOGIN_USERNAME`、`LOGIN_PASSWORD`、`INVALID_LOGIN_PASSWORD`、`LOGIN_ENDPOINT` 和 `target_base_url_env` 指定的 base URL 环境变量。要真正执行该 adapter，需要显式设置 `skip_by_default=false` 并配置目标服务地址和测试账号。

请求示例：

```json
{
  "cases": [
    {
      "id": "TC-001",
      "title": "有效手机号和验证码登录成功",
      "precondition": "用户已注册，验证码未过期。",
      "steps": ["输入手机号", "输入验证码", "点击登录"],
      "expected": ["登录成功"],
      "type": "functional"
    }
  ],
  "filename": "login_generated_cases.py",
  "target_base_url_env": "LOGIN_BASE_URL",
  "skip_by_default": true,
  "adapter": "template"
}
```

登录 API adapter 示例：

```json
{
  "cases": [
    {
      "id": "TC-LOGIN-001",
      "title": "有效账号密码登录成功",
      "precondition": "测试账号已存在。",
      "steps": ["输入用户名", "输入正确密码", "提交登录"],
      "expected": ["登录成功"],
      "type": "functional"
    }
  ],
  "filename": "login_api_cases.py",
  "target_base_url_env": "LOGIN_BASE_URL",
  "skip_by_default": false,
  "adapter": "login_api"
}
```

### 5.5 生成测试计划

```http
POST /api/v1/test-plans/generate
```

输入需求描述、结构化需求点和可选知识库上下文，返回 `TestPlan`。默认使用规则 planner；如果需要真实模型生成，设置 `use_llm=true`。`allow_llm_fallback=false` 时，模型调用或输出校验失败会直接返回错误，不回退到规则 planner。

请求示例：

```json
{
  "description": "订单退款接口需要支持创建退款、幂等冲突和无权限拒绝。",
  "requirements": [
    {
      "id": "REFUND-001",
      "title": "创建退款 API",
      "description": "POST /api/v1/refunds 创建退款，重复 idempotency_key 需要返回冲突。",
      "keywords": ["POST /api/v1/refunds", "idempotency_key", "冲突"],
      "priority": "critical"
    }
  ],
  "max_steps": 3,
  "use_llm": true,
  "allow_llm_fallback": true
}
```

### 5.6 执行测试计划

```http
POST /api/v1/test-plans/execute-step
POST /api/v1/test-plans/execute
POST /api/v1/test-plans/execution-jobs
GET /api/v1/test-plans/execution-jobs
GET /api/v1/test-plans/execution-jobs/{job_id}
POST /api/v1/test-plans/reports/export
```

`execute-step` 执行单个 `TestPlanStep` 并返回 `ToolRun`。`execute` 执行整份 `TestPlan` 并返回 `TestExecutionReport`。默认注册 HTTP adapter；`manual` 步骤会返回 `skipped`，未注册工具会返回 `blocked`。如果配置了 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST`，`http_base_url` 必须命中 allowlist。pytest adapter 默认关闭，只有设置 `TEST_TOOL_PYTEST_ENABLED=true` 后才会注册，并受 `TEST_TOOL_PYTEST_ALLOWED_PATHS` 限制。HTTP 响应摘要和 pytest stdout/stderr 会写入 `TEST_TOOL_ARTIFACT_DIR`，路径返回在 `ToolRun.artifact_paths`。单个 artifact 文件受 `TEST_TOOL_ARTIFACT_MAX_BYTES` 截断保护，过期 artifact 可通过 `scripts/cleanup_tool_artifacts.py` 按 `TEST_TOOL_ARTIFACT_RETENTION_SECONDS` 清理。

`execution-jobs` 提供异步执行入口，提交请求后返回 `queued/running/succeeded/failed` 状态，可通过列表和详情接口查询执行报告。默认 `GENERATION_JOB_QUEUE_BACKEND=in_memory` 时使用 API 进程内 worker；设置 `GENERATION_JOB_QUEUE_BACKEND=rq` 后，测试计划执行 job 会写入 `GENERATION_HISTORY_DB_PATH` 指向的 SQLite store，并派发到 Redis/RQ，由 `scripts/run_generation_worker.py` 监听同一队列执行。服务或 worker 启动时会把超过 `GENERATION_JOB_STALE_AFTER_SECONDS` 仍处于 `running` 的测试计划执行任务标记为 failed。

`reports/export` 接收结构化 `TestExecutionReport`，支持 `format=markdown` 或 `format=json`，返回可下载文件。Markdown 报告由 `ToolRun`、需求覆盖、缺陷和建议确定性渲染，不调用 LLM 重新总结；JSON 导出保留原始报告 schema，适合后续测评或归档。

`http_base_url` 必须是明确的 HTTP/HTTPS base URL，步骤中的 HTTP path 只能是相对路径，不能传入完整外部 URL。

单步骤请求示例：

```json
{
  "http_base_url": "http://127.0.0.1:8000",
  "step": {
    "id": "TP-001",
    "title": "验证创建退款",
    "objective": "调用创建退款接口",
    "requirement_ids": ["REFUND-001"],
    "test_types": ["functional"],
    "priority": "critical",
    "tool": "http",
    "tool_args": {
      "method": "POST",
      "path": "/api/v1/refunds",
      "expected_status": [200, 201],
      "json": {"idempotency_key": "k-1"}
    },
    "success_criteria": ["创建退款成功"]
  }
}
```

整计划请求示例：

```json
{
  "http_base_url": "http://127.0.0.1:8000",
  "plan": {
    "id": "plan-refund",
    "title": "退款接口测试计划",
    "steps": [
      {
        "id": "TP-001",
        "title": "验证创建退款",
        "objective": "调用创建退款接口",
        "requirement_ids": ["REFUND-001"],
        "tool": "http",
        "tool_args": {"path": "/api/v1/refunds", "expected_status": 200}
      }
    ]
  }
}
```

### 5.7 测试 Agent workflow job

```http
POST /api/v1/test-agent/workflow-jobs
GET /api/v1/test-agent/workflow-jobs
GET /api/v1/test-agent/workflow-jobs/{job_id}
```

workflow job 从需求开始执行完整链路：生成 `TestPlan`，调用工具 adapter，汇总 `TestExecutionReport`。它适合 `use_llm=true` 的真实模型路径，因为提交接口会立即返回 202 和 job id，调用方轮询详情接口获取最终 `result.plan` 和 `result.report`。

请求示例：

```json
{
  "generation_request": {
    "description": "订单退款接口需要支持创建退款、幂等冲突和无权限拒绝。",
    "requirements": [],
    "context": [],
    "max_steps": 5,
    "use_llm": true,
    "allow_llm_fallback": false
  },
  "http_base_url": "http://127.0.0.1:8000"
}
```

job 状态为 `queued/running/succeeded/failed`。成功时详情包含 `result.plan`、`result.report` 和 `result.timing`；失败时包含 `error.code`、`error.message`、`error.stage` 和失败前已记录的 `error.timing`。`job.timing` 会从 job 时间戳和结果中派生排队耗时、任务运行耗时、总耗时、计划生成耗时、工具执行耗时和报告汇总耗时。阶段失败码按失败位置区分，例如真实 LLM 计划生成超时会记录为 `plan_generation_timeout`。该接口复用现有 `GENERATION_JOB_QUEUE_BACKEND=in_memory|rq`、SQLite/MySQL store、Redis/RQ worker 和 stale running 恢复。`scripts/check_test_agent_workflow_queue.py` 可检查 workflow job 数据库状态与 RQ registry 是否一致；`scripts/smoke_test_agent_workflow_rq_mysql.py` 可在 Docker MySQL profile 中验证真实 API、Redis、MySQL、RQ worker、HTTP adapter、artifact、报告、耗时汇总、吞吐汇总和队列 alert 的完整链路；前端测试计划工作台已支持提交 workflow job、查看列表/详情、轮询活跃任务、展示耗时和 LLM 调用指标并回填结果。真实 LLM benchmark、重试/backoff 和 workflow 吞吐门禁已具备可选验证入口。

### 5.8 评估需求覆盖率

```http
POST /api/v1/evaluation/coverage
```

输入需求验收点和测试用例，返回需求覆盖率、关键词覆盖率、未覆盖需求 ID、匹配用例和缺失关键词。该接口是确定性规则初筛，不能替代人工需求评审。

请求示例：

```json
{
  "requirements": [
    {
      "id": "REQ-LOGIN-001",
      "title": "有效手机号和验证码登录成功",
      "keywords": ["有效验证码", "登录成功"],
      "priority": "high"
    }
  ],
  "cases": [
    {
      "id": "TC-001",
      "title": "手机号验证码登录成功",
      "precondition": "用户已注册。",
      "steps": ["输入手机号", "输入验证码", "点击登录"],
      "expected": ["登录成功"],
      "type": "functional"
    }
  ],
  "min_keyword_match_ratio": 1.0
}
```

### 5.9 沉淀覆盖缺口到知识库

```http
POST /api/v1/evaluation/coverage/gaps/knowledge
```

输入覆盖率评估结果，服务会把人工确认后的未覆盖需求整理成一篇知识库文档，并通过 RAG upsert 写入指定 `source`。默认只写入未覆盖项；`include_covered=true` 时可连同已覆盖项一起归档。

请求示例：

```json
{
  "coverage": {
    "total_requirements": 1,
    "covered_requirements": 0,
    "coverage_rate": 0,
    "total_keywords": 2,
    "matched_keywords": 1,
    "keyword_coverage_rate": 0.5,
    "uncovered_requirement_ids": ["REQ-LOGIN-002"],
    "items": [
      {
        "requirement": {
          "id": "REQ-LOGIN-002",
          "title": "验证码错误提示",
          "description": "验证码错误时需要明确提示。",
          "keywords": ["验证码错误", "提示"],
          "priority": "high",
          "source": "prd-login"
        },
        "covered": false,
        "coverage_score": 0.5,
        "matched_case_ids": [],
        "matched_case_titles": [],
        "matched_keywords": ["验证码错误"],
        "missing_keywords": ["提示"]
      }
    ],
    "warnings": ["uncovered_requirements"],
    "recommendations": ["补充未覆盖验收点对应的测试用例：REQ-LOGIN-002。"]
  },
  "source": "knowledge/evaluation/login-coverage-gaps.md",
  "module": "login",
  "tags": ["coverage-gap", "login"],
  "chunk_size": 900
}
```

返回会包含 `source`、`version`、`added_chunks`、`replaced_chunks` 和 `gap_count`。前端覆盖率页已提供“确认沉淀缺口”入口。

### 5.10 导入知识库

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

### 5.11 查询知识库

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

### 5.12 管理知识库文档

```http
GET /api/v1/knowledge/documents
POST /api/v1/knowledge/documents/upsert
DELETE /api/v1/knowledge/documents?source=knowledge/prd/login.md
```

文档管理接口用于查看当前索引里的文档清单、按 `source` 更新单个文档、按 `source` 删除文档。upsert 会替换同 `source` 的旧 chunk，并把当前文档版本号加 1。

### 5.13 查询和处理门控记录

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

### 5.14 查询内部运行指标

```http
GET /api/v1/operations/metrics
GET /api/v1/operations/metrics/prometheus
```

运行指标接口受同一套 `X-API-Key` 保护，面向内部监控和受控运维使用，不建议公网直接暴露。

`/operations/metrics` 返回 JSON，包含 readiness 状态、数据库 backend、生成任务、测试计划执行任务、测试 Agent workflow 任务的状态计数，生成历史成功/失败和 generation gate 状态计数，队列 backend/RQ registry/worker 计数，HTTP 请求量/状态码/耗时桶，LLM 配置状态、模型名、timeout 和 retry 配置，以及生成、测试计划执行、测试 Agent workflow 的业务阶段计数和耗时桶。

`/operations/metrics/prometheus` 返回 Prometheus text exposition，当前包含：

- `ai_testcase_ready`
- `ai_testcase_llm_configured`
- `ai_testcase_llm_timeout_seconds`
- `ai_testcase_llm_max_retries`
- `ai_testcase_llm_call_total`
- `ai_testcase_llm_attempt_total`
- `ai_testcase_llm_retry_total`
- `ai_testcase_llm_call_duration_seconds`
- `ai_testcase_stage_total`
- `ai_testcase_stage_duration_seconds`
- `ai_testcase_job_count`
- `ai_testcase_job_active_count`
- `ai_testcase_generation_record_count`
- `ai_testcase_generation_gate_count`
- `ai_testcase_generation_usage_tokens`
- `ai_testcase_generation_estimated_cost`
- `ai_testcase_rq_registry_jobs`
- `ai_testcase_rq_worker_count`
- `ai_testcase_readiness_check_status`
- `ai_testcase_http_requests_total`
- `ai_testcase_http_request_duration_seconds`

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
APP_API_KEYS
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
LLM_RETRY_BACKOFF_SECONDS
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
TEST_TOOL_PYTEST_ENABLED
TEST_TOOL_HTTP_BASE_URL_ALLOWLIST
TEST_TOOL_HTTP_ALLOWED_HEADERS
TEST_TOOL_ARTIFACT_DIR
TEST_TOOL_ARTIFACT_MAX_BYTES
TEST_TOOL_ARTIFACT_RETENTION_SECONDS
TEST_TOOL_PYTEST_ALLOWED_PATHS
TEST_TOOL_PYTEST_TIMEOUT_SECONDS
TEST_TOOL_PYTEST_ENV_ALLOWLIST
RATE_LIMIT_ENABLED
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
REQUEST_LOG_ENABLED
REQUEST_LOG_FORMAT
DATABASE_BACKEND
DATABASE_URL
GENERATION_HISTORY_ENABLED
GENERATION_HISTORY_DB_PATH
CORS_ALLOW_ORIGINS
CORS_ALLOW_CREDENTIALS
```

项目也兼容读取当前已有的 `.env/config.py`。

注意：`.env/config.py` 里如果有真实 API Key 或服务调用密钥，不要提交到版本库。除 `/health` 外，业务接口需要在请求头携带 `X-API-Key`。服务接受 `APP_API_KEY` 单 key，也接受逗号分隔的 `APP_API_KEYS` 多 key；多 key 适合滚动轮换服务调用密钥。服务会为响应增加 `X-Request-ID` 和 `X-Process-Time-ms`，并默认对 `/api/v1/*` 做内存级限流。请求日志默认是文本格式，也可以设置 `REQUEST_LOG_FORMAT=json` 便于容器和集中日志系统采集。生成接口默认把生成请求、响应、失败原因和耗时写入 `DATABASE_BACKEND=sqlite`、`GENERATION_HISTORY_DB_PATH` 指向的 SQLite 数据库；`DATABASE_BACKEND=mysql` 代码路径已实现并通过本机 Docker MySQL smoke，依赖已纳入统一 `requirements.txt`，启用前需要初始化 schema。异步生成可使用进程内 worker 或 Redis/RQ 外部队列；直接在 WSL/本机 Python 运行时可用 `REDIS_URL=redis://127.0.0.1:6379/0`，Docker Compose 内部使用 `REDIS_URL=redis://redis:6379/0`。测试计划执行接口默认启用 HTTP adapter，可通过 `TEST_TOOL_HTTP_BASE_URL_ALLOWLIST` 收紧允许访问的目标服务，并通过 `TEST_TOOL_HTTP_ALLOWED_HEADERS` 限制可转发 header；工具执行证据写入 `TEST_TOOL_ARTIFACT_DIR`，并受 `TEST_TOOL_ARTIFACT_MAX_BYTES` 限制；`TEST_TOOL_ARTIFACT_RETENTION_SECONDS` 控制 `scripts/cleanup_tool_artifacts.py` 的过期清理窗口；artifact 下载接口只允许读取 artifact 根目录内文件。pytest adapter 需要显式设置 `TEST_TOOL_PYTEST_ENABLED=true`，并受 `TEST_TOOL_PYTEST_ALLOWED_PATHS`、`TEST_TOOL_PYTEST_TIMEOUT_SECONDS` 和 `TEST_TOOL_PYTEST_ENV_ALLOWLIST` 控制。`AGENT_WORKFLOW_BACKEND` 默认使用 `langgraph`；`local` backend 保留为 fallback 和行为对照。Reviewer 默认开启并写入 `metadata.review`；自动重试默认关闭，避免隐式增加 LLM 成本。

生产环境应设置 `APP_ENV=production`。此时应用会在启动时强制校验关键配置，包括真实服务密钥、真实模型密钥、HTTPS CORS 来源、语义 embedding、限流、请求日志、Agent Reviewer 和持久化历史库路径；校验失败会拒绝启动。

## 11. 如何启动

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 是唯一后端安装入口，包含 API、worker、RAG、MySQL backend、测试和 lint 所需依赖。语义 embedding 依赖体积较大，不进入默认安装；需要 `EMBEDDING_PROVIDER=sentence_transformers` 时，按部署文档中的可选安装命令单独安装。

启动服务：

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py --host 127.0.0.1 --port 8000
```

访问接口文档：

```text
http://127.0.0.1:8000/docs
```

启动前端工作台：

```powershell
cd frontend
npm install --ignore-scripts --omit=optional
npm run dev
```

前端默认访问 `http://127.0.0.1:5173`，开发模式通过 Vite proxy 转发到本地 FastAPI。更多前端配置、测试和构建说明见 [frontend/README.md](../frontend/README.md)。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端测试和构建：

```powershell
cd frontend
npm test
npm run build
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
- 如果需要 Excel，调用 Excel 导出接口。
- 如果需要推进自动化落地，调用 pytest 导出接口；默认模板由测试人员补充真实执行逻辑，登录 API 场景可先使用 `adapter=login_api` 示例。
- 如果需要检查覆盖缺口，调用覆盖率评估接口，把 PRD 验收点和生成用例做映射。

推荐集成边界：

- 这个服务负责 AI 生成、RAG、格式校验。
- 仓库内置前端工作台负责本地操作和演示。
- 外部平台或后续生产级后台负责用户体系、权限、项目管理、用例审批和落库。

## 14. 后续扩展点

可以优先扩展这些方向：

- 替换更强的 embedding 模型，提高 RAG 召回质量。
- 增加文件上传接口，支持上传 PRD、Word、PDF。
- 增加测试管理平台 adapter，例如禅道、TestRail、飞书多维表格。
- 补齐 MySQL 生产化：连接池参数、长时间稳定性验证、高并发验证和默认 backend 切换评估。
- 增强 Redis/RQ 队列治理，例如原子背压、队列指标、失败率统计和 worker 运行时长监控。
- 增强用例质量评分，例如覆盖率、风险等级和人工验收结果回流。
- 增强覆盖率评估，例如同义词、权重、语义相似度和人工确认结果回流。
- 扩展更多可执行自动化 adapter，例如支付、退款或 UI 自动化示例。
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
- pytest 模板导出。
- 需求覆盖率评估。

它适合作为第一个可集成版本。后续重点不是重写架构，而是增强知识库质量、模型稳定性、平台集成和权限安全。
