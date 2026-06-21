# 项目问题跟踪

最后更新：2026-06-21

## 维护规则

- 状态使用：`open`、`in_progress`、`done`、`wontfix`。
- 严重级别使用：`critical`、`high`、`medium`、`low`。
- 新问题按编号递增；修复后保留条目并更新状态、修复版本或验证方式。
- 每次改动相关模块后，至少运行 `.\.venv\Scripts\python.exe -m pytest -q`，并在条目中补充验证结果。

## 当前概览

| 编号 | 严重级别 | 状态 | 标题 |
| --- | --- | --- | --- |
| ISSUE-001 | high | done | API 缺少鉴权，知识导入和生成接口可被任意调用 |
| ISSUE-002 | high | done | CORS 默认允许所有来源且启用凭据 |
| ISSUE-003 | high | done | Excel 导出文件名未校验，可能造成响应头注入或下载异常 |
| ISSUE-004 | medium | done | `_normalize_payload` 对顶层 list 的兼容逻辑不可达且会抛错 |
| ISSUE-005 | medium | done | 用例 ID 自动补全逻辑被字段校验阻断 |
| ISSUE-006 | medium | done | LLM 重试配置缺少下限校验，负数会导致无请求并返回无意义错误 |
| ISSUE-007 | medium | done | RAG 使用 hash embedding，仅适合演示，生产召回质量不可控 |
| ISSUE-008 | medium | done | LLM/RAG/API 主链路缺少集成测试和失败路径测试 |
| ISSUE-009 | low | done | 启动脚本重定向标准输出，控制台启动时缺少即时反馈 |
| ISSUE-010 | low | done | 工作区包含运行产物，需继续依赖忽略规则避免污染版本库 |
| ISSUE-011 | medium | done | 缺少 Docker、CI 和部署说明，GitHub 交付基线不足 |
| ISSUE-012 | high | in_progress | 公网生产仍缺少限流、结构化日志、监控和 HTTPS 网关 |
| ISSUE-013 | medium | done | 生成结果未落库，无法审计、回放和统计生成质量 |
| ISSUE-014 | medium | done | 知识库缺少文档级更新、删除和当前版本管理能力 |
| ISSUE-015 | medium | done | 生成历史缺少质量评分，难以筛选和回放低质量结果 |
| ISSUE-016 | high | done | 生产环境缺少启动前配置校验，可能带不安全默认值上线 |
| ISSUE-017 | medium | done | 缺少可直接复用的生产运行入口和容器健康检查 |
| ISSUE-018 | medium | done | 缺少 LLM 用量与估算成本统计，难以做费用治理 |
| ISSUE-019 | medium | done | 生成链路缺少显式 Agent 工作流和架构讲解文档 |
| ISSUE-020 | medium | done | Agent 工作流缺少显式状态对象和节点抽象，后续迁移框架成本偏高 |
| ISSUE-021 | medium | done | 生成后缺少 Reviewer Agent 和条件修复路径，低质量结果只能事后发现 |
| ISSUE-022 | medium | done | RAG 初次召回不足时缺少 query rewrite 条件边，容易直接带空上下文生成 |
| ISSUE-023 | medium | done | Agent 缺少成本和质量门控，无法在高成本或低质量场景停止自动流程 |
| ISSUE-024 | medium | done | 门控失败响应缺少结构化 human-in-the-loop 信息，调用方难以接审批流 |
| ISSUE-025 | medium | done | 门控事件未持久化为待处理视图，人工介入缺少查询入口 |

## 问题详情

### ISSUE-001 API 缺少鉴权，知识导入和生成接口可被任意调用

- 严重级别：`high`
- 状态：`done`
- 位置：`app/api/routes.py:46`、`app/api/routes.py:58`、`app/api/routes.py:69`、`app/api/routes.py:76`
- 影响：生成、导出、知识导入和知识查询接口没有认证依赖。服务一旦暴露到内网或公网，任何调用方都可以消耗 LLM 额度、写入知识库或读取检索片段。
- 建议：增加 API key、JWT 或上游网关鉴权；至少对 `/knowledge/ingest` 和 `/test-cases/generate` 做服务端认证和调用频控。
- 修复：`/api/v1/*` 业务接口已统一要求 `X-API-Key`；未配置 `APP_API_KEY` 时返回 503，缺失或错误密钥返回 401。`/health` 保持公开。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `13 passed, 1 warning`。

### ISSUE-002 CORS 默认允许所有来源且启用凭据

- 严重级别：`high`
- 状态：`done`
- 位置：`app/core/config.py:66`、`app/main.py:11`
- 影响：`cors_allow_origins` 默认是 `["*"]`，应用同时设置 `allow_credentials=True`。这既不适合生产安全边界，也可能在浏览器凭据请求场景下产生不可预期的 CORS 行为。
- 建议：从环境变量读取明确的允许来源列表；生产环境禁止 `*` 与凭据同时启用；为本地开发单独保留宽松配置。
- 修复：新增 `CORS_ALLOW_ORIGINS` 和 `CORS_ALLOW_CREDENTIALS` 配置；默认只允许本地开发来源且凭据关闭；当来源包含 `*` 时会强制关闭凭据。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `13 passed, 1 warning`。

### ISSUE-003 Excel 导出文件名未校验，可能造成响应头注入或下载异常

- 严重级别：`high`
- 状态：`done`
- 位置：`app/models/test_case.py:130`、`app/api/routes.py:63`、`app/api/routes.py:67`、`app/api/routes.py:85`
- 影响：`filename` 直接进入 `Content-Disposition` 响应头，没有过滤 CR/LF、引号、路径分隔符或超长值。恶意或异常文件名可能导致响应头注入、下载失败或客户端表现不一致。
- 建议：在模型层限制文件名字符集和长度；服务端统一追加 `.xlsx`；响应头同时支持安全 ASCII `filename` 和 RFC 5987 `filename*`。
- 修复：`ExportRequest.filename` 已校验非法字符、长度和后缀；导出响应头已改为安全 ASCII fallback 加 UTF-8 `filename*`。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `13 passed, 1 warning`。

### ISSUE-004 `_normalize_payload` 对顶层 list 的兼容逻辑不可达且会抛错

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/generator.py:53`
- 影响：函数看起来想兼容 LLM 直接返回 list，但实际先执行 `payload.get(alias)`，当 `payload` 是 list 时会抛出 `AttributeError: 'list' object has no attribute 'get'`，无法进入后面的 list 分支。
- 复现：`.\.venv\Scripts\python.exe -c "from app.services.generator import _normalize_payload; _normalize_payload([{'id':'TC-001'}])"`
- 建议：先判断 `isinstance(payload, list)`，再处理 dict 别名；同时补充单元测试覆盖顶层 list、`test_cases`、`items` 等变体。
- 修复：`_normalize_payload()` 已先处理顶层 list，并对非 dict payload 返回 `{"cases": payload}`，避免 `.get()` 抛错。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `4 passed`。

### ISSUE-005 用例 ID 自动补全逻辑被字段校验阻断

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/models/test_case.py:55`、`app/models/test_case.py:90`
- 影响：`ensure_case_ids()` 试图为空 ID 补 `TC-001`，但 `id` 字段是必填且 `min_length=1`。当 LLM 返回 `null`、空字符串或漏掉 ID 时，字段校验会先失败，自动补全不会执行。
- 复现：`id=None` 的用例会返回 `('cases', 0, 'id') string_too_short`。
- 建议：如果 ID 允许后端补全，将 `id` 调整为可选并在 `model_validator(mode="before")` 或集合归一化阶段补齐；如果不允许补全，则删除当前无效的自动补全逻辑。
- 修复：`TestCase.id` 已允许缺省或空字符串，由 `TestCaseCollection.ensure_case_ids()` 统一按顺序补齐。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `4 passed`。

### ISSUE-006 LLM 重试配置缺少下限校验，负数会导致无请求并返回无意义错误

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/core/config.py:47`、`app/core/config.py:106`、`app/services/llm.py:39`
- 影响：`LLM_MAX_RETRIES=-1` 可被接受，`LLMClient.generate_json()` 会跳过请求循环并报 `LLM request failed: None`，不利于排障。
- 建议：对 `llm_max_retries` 设置 `ge=0`，对 `llm_timeout_seconds` 设置合理下限；非法配置应在启动时失败或回退并记录明确告警。
- 修复：`LLM_MAX_RETRIES` 低于 0、`LLM_TIMEOUT_SECONDS` 低于 1 或无法解析时会回退到默认值。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `13 passed, 1 warning`。

### ISSUE-007 RAG 使用 hash embedding，仅适合演示，生产召回质量不可控

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/rag.py:16`
- 影响：当前 embedding 基于 token hash，无法理解语义相似性。知识库规模变大后，相关片段召回质量不可控，进而影响测试用例准确性。
- 建议：抽象 embedding provider，支持智谱 embedding、bge、text2vec 或企业内部向量服务；保留 hash embedding 作为本地 demo fallback，并在配置中明确标识。
- 修复：RAG 已支持 `EMBEDDING_PROVIDER=hash|sentence_transformers`，本地已切换到 `BAAI/bge-small-zh-v1.5`，模型缓存位于 `.model_cache/huggingface`，并使用新 collection `test_knowledge_bge_small_zh_v15` 避免维度冲突。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `18 passed, 2 warnings`；本地配置已完成一次 sentence-transformers 导入和检索烟测。

### ISSUE-008 LLM/RAG/API 主链路缺少集成测试和失败路径测试

- 严重级别：`medium`
- 状态：`done`
- 位置：`tests/test_generator.py`、`tests/test_generate_api.py`、`tests/test_rag.py`、`tests/test_rag_evaluation.py`、`tests/test_export.py`、`tests/test_auth.py`、`tests/test_config.py`
- 影响：当前测试只覆盖模型归一化的一条路径。未覆盖 API 响应、Excel 导出、RAG chunk/search、LLM 错误映射、`_normalize_payload` 兼容逻辑、配置异常等关键行为。
- 当前验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `37 passed, 2 warnings`。
- 建议：增加 FastAPI TestClient 测试、RAG 使用临时目录测试、LLM mock 测试、Excel 内容测试和错误路径测试。
- 修复：已补充模型、导出、鉴权、配置、RAG provider、导入脚本、RAG 评估、生成器 mock 链路和生成 API 错误映射测试。生成链路覆盖正常返回、别名 payload、顶层 list、校验失败重试、失败耗尽、LLM 异常、RAG 空结果、上下文返回、截断、去重和 ID 重排。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `37 passed, 2 warnings`。

### ISSUE-009 启动脚本重定向标准输出，控制台启动时缺少即时反馈

- 严重级别：`low`
- 状态：`done`
- 位置：`scripts/run_server.py:21`
- 影响：脚本启动后 stdout/stderr 被写入日志文件，命令行用户看不到服务地址、启动失败原因或 uvicorn 实时输出，排障体验较差。
- 建议：增加 `--log-to-file` 开关或同时输出到控制台和文件；`start_server.cmd` 使用后台启动时再默认写入日志。
- 修复：`scripts/run_server.py` 默认保留控制台输出，并新增 `--log-to-file` 后台日志开关；`scripts/start_server.cmd` 使用后台日志模式。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `39 passed, 2 warnings`。

### ISSUE-010 工作区包含运行产物，需继续依赖忽略规则避免污染版本库

- 严重级别：`low`
- 状态：`done`
- 位置：`.gitignore:2`、`.gitignore:5`、`.gitignore:9`、`.gitignore:11`
- 影响：当前工作区存在 `__pycache__/`、`.pytest_cache/`、`logs/`、`data/chroma/` 等运行产物。`.gitignore` 已覆盖这些路径，但本目录当前不是 Git 仓库，后续初始化或迁移仓库时仍需确认不会误提交。
- 建议：保留现有忽略规则；初始化仓库或迁移代码前执行一次状态检查，确认缓存、日志和向量库数据未进入版本控制。
- 修复：`.gitignore` 已补充覆盖 `.env.*`、coverage 产物、构建产物和 `knowledge_export/`；新增 `.dockerignore`，避免 Docker 构建上下文带入密钥、模型缓存、Chroma 数据、日志和私有知识导出。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `39 passed, 2 warnings`；已执行 `git init` 和 `git status --ignored --short`，确认 `.env/`、`.model_cache/`、`data/`、`logs/`、`knowledge_export/` 等运行或私有数据被忽略。

### ISSUE-011 缺少 Docker、CI 和部署说明，GitHub 交付基线不足

- 严重级别：`medium`
- 状态：`done`
- 位置：`Dockerfile`、`.dockerignore`、`.github/workflows/ci.yml`、`docs/deployment.md`、`README.md`
- 影响：项目虽然可以本地运行，但缺少容器化入口、自动化测试工作流和部署说明，放入 GitHub 后接手者难以判断如何安装、验证和避免提交敏感数据。
- 建议：补充最小 Dockerfile、GitHub Actions 测试工作流、部署说明和 README 入口；文档中明确真实 key、模型缓存、向量库和私有知识库不进入仓库。
- 修复：已新增 Docker 构建文件、Docker 忽略规则、Windows CI 工作流和部署发布说明；README 已链接部署文档并补充 Docker 运行方式。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `39 passed, 2 warnings`。

### ISSUE-012 公网生产仍缺少限流、结构化日志、监控和 HTTPS 网关

- 严重级别：`high`
- 状态：`in_progress`
- 位置：`app/core/middleware.py`、`app/core/config.py`、`app/main.py`、部署入口
- 影响：当前服务已经有基础 API key 鉴权，但如果直接暴露到公网，仍缺少调用频控、请求审计、结构化日志、错误监控、HTTPS 终止和上游网关策略。攻击者一旦拿到服务 key，仍可能快速消耗 LLM 额度或批量读取检索结果。
- 建议：上线前接入反向代理或 API 网关，增加限流、访问日志、请求耗时日志、异常告警和 HTTPS；应用层可补充请求 ID、生成接口并发限制和敏感日志脱敏。
- 部分修复：应用层已新增 `X-Request-ID`、`X-Process-Time-ms`、请求耗时日志和 `/api/v1/*` 内存级限流；配置项包括 `RATE_LIMIT_ENABLED`、`RATE_LIMIT_REQUESTS`、`RATE_LIMIT_WINDOW_SECONDS` 和 `REQUEST_LOG_ENABLED`。
- 剩余风险：内存限流只适合单进程基础防护，不能替代多实例共享限流、WAF、HTTPS、集中日志和监控告警。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `44 passed, 2 warnings`。

### ISSUE-013 生成结果未落库，无法审计、回放和统计生成质量

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/history.py`、`app/api/routes.py`、`app/models/test_case.py`
- 影响：此前生成接口只把结果返回给调用方，服务端不保存输入、输出、失败原因或耗时。后续无法做历史记录页面、质量回放、问题排查、成本统计或提示词版本对比。
- 建议：增加生成记录持久化，保存请求、响应、metadata、失败原因、耗时和 request id；提供列表和详情查询接口；运行数据不能进入 Git 仓库。
- 修复：新增 SQLite 生成历史存储，默认写入 `GENERATION_HISTORY_DB_PATH=data/app.sqlite3`；`POST /api/v1/test-cases/generate` 成功和失败都会记录；新增 `GET /api/v1/generation-records` 和 `GET /api/v1/generation-records/{record_id}`；`.gitignore` 和 `.dockerignore` 已排除 SQLite 运行数据。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `49 passed, 2 warnings`。

### ISSUE-014 知识库缺少文档级更新、删除和当前版本管理能力

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/rag.py`、`app/api/routes.py`、`app/models/test_case.py`
- 影响：此前知识库主要支持批量导入和整体 reset。真实使用中某个 PRD、接口文档或规范更新时，无法按 `source` 精确替换或删除，容易让旧 chunk 残留在检索结果里，影响生成准确性。
- 建议：为知识库增加文档清单、按 source upsert、按 source delete，并在 chunk metadata 记录当前版本、内容 hash 和更新时间。
- 修复：新增 `GET /api/v1/knowledge/documents`、`POST /api/v1/knowledge/documents/upsert`、`DELETE /api/v1/knowledge/documents?source=...`；RAG metadata 新增 `version`、`content_hash`、`updated_at`；upsert 会先删除同 source 旧 chunk，再写入新 chunk 并递增版本。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `53 passed, 3 warnings`。

### ISSUE-015 生成历史缺少质量评分，难以筛选和回放低质量结果

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/quality.py`、`app/services/history.py`、`app/models/test_case.py`
- 影响：已有生成历史可以保存输入和输出，但缺少可解释的质量摘要。后续做历史回放、人工审核、质量趋势统计时，需要人工逐条判断是否覆盖核心类型、是否重复、是否有知识库支撑。
- 建议：先实现不调用大模型的确定性评分，覆盖用例数量、重复标题、目标类型覆盖、步骤/预期完整度和知识库 grounding；评分结果随历史详情返回。
- 修复：新增 `GenerationQualityReport` 和本地评分服务；`GET /api/v1/generation-records/{record_id}` 对成功记录返回 `quality`，失败记录返回 `quality=null`。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `56 passed, 3 warnings`。

### ISSUE-016 生产环境缺少启动前配置校验，可能带不安全默认值上线

- 严重级别：`high`
- 状态：`done`
- 位置：`app/core/config.py`、`app/main.py`
- 影响：此前开发默认配置可以直接启动。如果部署时误用默认 CORS、本地 hash embedding、占位 key、关闭限流或内存历史库，服务可能在看似正常的状态下进入生产环境，带来安全、质量和审计风险。
- 建议：增加 `APP_ENV`；当 `APP_ENV=production` 时，在应用启动阶段强制校验生产关键配置，不满足要求直接拒绝启动。
- 修复：新增 `APP_ENV` 和 `validate_startup_settings()`；生产环境会校验真实 `APP_API_KEY`、真实 `ZHIPU_API_KEY`、HTTPS CORS 来源、非 `hash` embedding、`EMBEDDING_LOCAL_FILES_ONLY=true`、启用限流、启用请求日志、启用生成历史和持久化历史库路径。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `63 passed, 3 warnings`。

### ISSUE-017 缺少可直接复用的生产运行入口和容器健康检查

- 严重级别：`medium`
- 状态：`done`
- 位置：`Dockerfile`、`docker-compose.yml`、`.env.runtime.example`、`docs/deployment.md`
- 影响：此前只有 Dockerfile 和手动 `docker run` 示例，部署者仍需自己拼装生产环境变量、持久化挂载和健康检查。实际部署时容易漏掉 `data/` 持久化、模型缓存挂载或健康检查。
- 建议：提供可提交的 runtime env 示例、Docker Compose 模板和容器健康检查；实际 `.env.runtime` 保持本地私有。
- 修复：新增 `.env.runtime.example`、`docker-compose.yml`，Dockerfile 增加 `/health` 健康检查；Compose 挂载 `data/` 和 `.model_cache/huggingface`，并使用 `.env.runtime` 作为本机运行配置。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `66 passed, 3 warnings`。

### ISSUE-018 缺少 LLM 用量与估算成本统计，难以做费用治理

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/usage.py`、`app/services/generator.py`、`app/services/history.py`、`app/models/test_case.py`
- 影响：此前历史记录包含模型、attempts、耗时和成功/失败，但没有 prompt/output 字符数、估算 token 和估算费用。后续难以做成本趋势、滥用排查和调用治理。
- 建议：在不调用真实 LLM 的前提下，先做本地估算统计；如果配置每千 token 单价，则返回估算费用。后续可替换为供应商真实 usage 字段或 tokenizer。
- 修复：新增 `GenerationUsage` 和本地 usage 估算服务；生成成功时写入 `metadata.usage`，历史列表和详情返回 `usage`；生成失败时尽量记录已产生的 prompt/output 估算；新增 `LLM_PROMPT_PRICE_PER_1K_TOKENS`、`LLM_COMPLETION_PRICE_PER_1K_TOKENS`、`LLM_COST_CURRENCY` 配置。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `70 passed, 3 warnings`。

### ISSUE-019 生成链路缺少显式 Agent 工作流和架构讲解文档

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/agent_workflow.py`、`app/services/generator.py`、`docs/agent-architecture.md`
- 影响：此前生成链路虽然已有 RAG、Prompt、LLM、校验和历史记录，但从代码和响应上看仍像线性服务调用，不利于解释 Agent 状态、节点职责、失败定位和后续迁移 LangGraph。
- 建议：先实现轻量工作流节点和 workflow trace，不急于引入重框架；同时维护一份文档解释记忆架构、上下文压缩、工作流设计、RAG、Tool Calling、评估和面试常见问题。
- 修复：新增 `WorkflowRecorder`、需求分析节点、测试策略规划节点；生成响应的 `metadata.workflow_steps` 返回节点轨迹；Prompt 注入测试策略规划；新增 `docs/agent-architecture.md` 讲解 Agent 架构和面试技术点。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `73 passed, 3 warnings`。

### ISSUE-020 Agent 工作流缺少显式状态对象和节点抽象，后续迁移框架成本偏高

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/agent_workflow.py`、`app/services/generator.py`、`docs/agent-architecture.md`
- 影响：上一阶段已有 workflow trace，但生成器仍主要依赖局部变量和 `WorkflowRecorder.run()` 串联。短期记忆没有显式状态对象，节点也不是独立的 state reader/writer；后续迁移 LangGraph、增加条件边或加入 Reviewer Agent 时需要再次重构。
- 建议：抽象 `GenerationWorkflowState` 和 `WorkflowNode`，让节点通过同一个 state 读写上下文，由 recorder 统一记录节点执行结果。
- 修复：新增 `GenerationWorkflowState` 承载 request、analysis、contexts、plan、attempt、prompt、payload、cases、usage 和 last_error；新增 `WorkflowNode` 与 `WorkflowRecorder.run_node()`；`TestCaseGenerator` 改为节点读写 state 的状态机形态；文档补充 state/node 与 LangGraph 映射关系。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `74 passed, 3 warnings`。

### ISSUE-021 生成后缺少 Reviewer Agent 和条件修复路径，低质量结果只能事后发现

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/reviewer.py`、`app/services/generator.py`、`app/services/prompt.py`、`app/core/config.py`
- 影响：此前生成成功只代表 JSON 结构通过校验，低覆盖、步骤过浅、缺少关键类型等质量问题主要依赖历史详情里的事后评分。Agent 链路缺少生成后审查和条件路由，难以表达“生成 -> 审查 -> 修复”的真实工作流。
- 建议：在后处理后增加 Reviewer 节点，复用本地质量评分形成可解释反馈；再增加条件边，允许在显式开启时把 Reviewer 反馈写回下一轮 Prompt。
- 修复：新增 `GenerationReview`、`review_generated_cases()` 和 `build_review_feedback()`；生成链路新增 `review_cases` 与 `route_after_review` 节点；`metadata.review` 返回审查结论；新增 `AGENT_REVIEW_ENABLED`、`AGENT_REVIEW_RETRY_ENABLED`、`AGENT_REVIEW_MIN_SCORE` 配置；默认审查开启、自动重试关闭，避免隐式增加 LLM 成本。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `78 passed, 3 warnings`。

### ISSUE-022 RAG 初次召回不足时缺少 query rewrite 条件边，容易直接带空上下文生成

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/query_rewrite.py`、`app/services/generator.py`、`app/services/agent_workflow.py`、`app/core/config.py`
- 影响：此前 RAG 初次召回为空或过少时，链路会直接进入 Planner 和 Prompt。模型仍可生成结果，但缺少企业知识 grounding，容易依赖输入描述和隐式假设。
- 建议：在 RAG 后增加条件路由；当召回数量低于阈值时，使用本地规则改写检索 query，并再检索一次。该逻辑不应默认调用 LLM，避免增加成本和不确定性。
- 修复：新增 `rewrite_knowledge_query()`；新增 `route_after_retrieval`、`rewrite_query`、`retrieve_rewritten_knowledge` 节点；`GenerationWorkflowState` 记录 `knowledge_query`、`rewritten_query`、`retrieval_attempts` 和检索重试决策；新增 `AGENT_QUERY_REWRITE_ENABLED`、`AGENT_QUERY_REWRITE_MIN_CHUNKS` 配置。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `83 passed, 3 warnings`。

### ISSUE-023 Agent 缺少成本和质量门控，无法在高成本或低质量场景停止自动流程

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/generator.py`、`app/core/config.py`、`app/api/routes.py`
- 影响：此前生成链路可以估算 usage、做 Reviewer 审查，但默认仍会继续执行或返回结果。对于超长 Prompt、高估算费用或 Reviewer 未通过的结果，系统缺少明确的“停止自动流程，交给人工确认”的边界。
- 建议：在 LLM 调用前增加预算门控；在 Reviewer 后增加可选强质量门控。门控失败应返回明确错误码，记录失败历史和 usage，不应伪装为成功响应。
- 修复：新增 `check_budget` 节点、`GenerationGateError`、`GenerationBudgetExceededError`、`GenerationQualityGateError`；API 将门控失败映射为 409；新增 `AGENT_BUDGET_MAX_PROMPT_TOKENS`、`AGENT_BUDGET_MAX_ESTIMATED_COST`、`AGENT_REVIEW_REQUIRE_PASS` 配置。默认阈值关闭，不改变现有行为。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `87 passed, 3 warnings`。

### ISSUE-024 门控失败响应缺少结构化 human-in-the-loop 信息，调用方难以接审批流

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/generator.py`、`app/api/routes.py`
- 影响：上一阶段门控失败虽然会返回 409，但 `detail` 只是字符串。前端或测试平台难以稳定判断是预算门控还是质量门控，也无法直接拿到 usage、review 和需要执行的人类动作。
- 建议：让门控错误携带结构化 detail，包括 code、gate、message、action_required、usage 和 review。API 保留 409 状态码，但返回机器可读 JSON。
- 修复：`GenerationGateError` 新增 `code`、`gate`、`action_required`、`usage`、`review` 和 `to_detail()`；预算门控返回 `budget_exceeded`/`human_confirmation`；质量门控返回 `quality_gate_failed`/`human_review`；API 409 的 `detail` 改为结构化 JSON。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `87 passed, 3 warnings`。

### ISSUE-025 门控事件未持久化为待处理视图，人工介入缺少查询入口

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/history.py`、`app/api/routes.py`、`app/models/test_case.py`
- 影响：门控失败已经能返回结构化 409，但落到历史里仍主要表现为普通失败记录。前端或测试平台要构建审批/复核列表时，需要自己从错误字符串里筛选，稳定性差。
- 建议：将 gate detail 作为结构化字段持久化，并提供单独的待处理门控查询接口。
- 修复：新增 `GenerationGateDetail`；SQLite 历史表新增 `gate_detail_json`；失败记录支持写入 gate detail；历史摘要和详情返回 `gate` 字段；新增 `GET /api/v1/generation-gates` 查询预算/质量门控触发的待处理记录。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `87 passed, 3 warnings`。

### ISSUE-026 门控事件缺少处理闭环，人工审批结果无法落库和审计

- 严重级别：`medium`
- 状态：`done`
- 位置：`app/services/history.py`、`app/api/routes.py`、`app/models/test_case.py`
- 影响：上一阶段已经可以查询门控事件，但事件仍停留在“待处理列表”层面。前端或外部测试平台即使完成了人工确认，也无法把 approved/rejected 结果写回服务端，后续审计、统计和待办清理都缺少可靠状态。
- 建议：为门控事件增加处理状态和处理人信息；列表接口默认只返回待处理记录，同时支持按状态查看全部、已批准和已驳回记录；处理接口应避免重复覆盖已关闭事件。
- 修复：新增 `GenerationGateResolution` 和 `GenerationGateResolveRequest`；SQLite 历史表新增 `gate_status`、`gate_resolved_at`、`gate_resolved_by`、`gate_resolution_comment`，旧 gate 记录自动补为 `pending`；`GET /api/v1/generation-gates` 支持 `status=pending|approved|rejected|all`；新增 `POST /api/v1/generation-gates/{record_id}/resolve` 将门控记录标记为 `approved` 或 `rejected`，重复处理返回 409。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q` 结果为 `87 passed, 3 warnings`。

## 本次检查记录

- 已读：`README.md`、`docs/project-guide.md`、`requirements.txt`、核心 `app/` 模块、`scripts/`、`tests/`。
- 已运行：`.\.venv\Scripts\python.exe -m pytest -q`
- 结果：`87 passed, 3 warnings`
- 限制：已完成健康检查和一次真实生成烟测；当前目录已初始化 Git，并已创建首次提交。
