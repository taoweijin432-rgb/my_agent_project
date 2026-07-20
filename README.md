# AI 测试用例生成助手

AI 测试用例生成助手是一个面向测试工程场景的 RAG Workflow Agent 后端服务。它接收自然语言需求、PRD 或历史用例材料，结合 Chroma 知识库检索结果，通过 LangGraph 编排生成链路，并用 Pydantic、Reviewer、门控、覆盖率评估和导出能力把模型输出整理成结构化测试资产。

当前版本包含 FastAPI API、LangGraph 工作流、Chroma RAG、智谱 LLM JSON Mode、同步/异步生成、Redis/RQ worker、SQLite/MySQL 存储、Excel/pytest 导出、覆盖率评估、React/Vite 前端工作台、Docker/Compose 和发布检查。

## 文档入口

- [文档总览](docs/README.md)
- [项目详细说明](docs/project-guide.md)
- [架构基线](docs/architecture-baseline.md)
- [Agent 架构](docs/agent-architecture.md)
- [本机运行](docs/local-run.md)
- [部署说明](docs/deployment.md)
- [发布检查](docs/release-checklist.md)
- [优化计划](docs/optimization-plan.md)
- [监控和告警](docs/monitoring.md)
- [RAG 评估](docs/rag-evaluation.md)
- [MySQL 运维](docs/mysql-operations.md)
- [前端工作台](frontend/README.md)
- [知识库目录](knowledge/README.md)

## 项目亮点

- 需求到报告闭环：支持从结构化需求生成测试计划，执行 HTTP/pytest/manual/sql 等测试步骤，并输出覆盖率、缺陷、原因分类、修复建议和 evidence。
- RAG 与质量门控：结合 Chroma 知识库、Reviewer、Schema 校验、覆盖矩阵和报告事实一致性检查，降低模型输出泛化和漏测风险。
- 真实模型验证：测试 Agent workflow 已覆盖 18 条需求到报告样本，真实 LLM strict eval 全量通过，质量结论以真实 LLM 路径为准，离线 deterministic eval 只作为快速回归保护。
- 工程化交付：具备 FastAPI、Redis/RQ、SQLite/MySQL、Docker Compose、React/Vite 前端、Prometheus 指标、发布检查、secret scan 和可选前端 release check。

## 推荐演示路径

1. 导入示例知识库：`./.venv/bin/python scripts/ingest_documents.py knowledge --recursive --reset`
2. 启动后端和前端工作台，进入测试计划页面。
3. 输入一组带 HTTP 状态码、权限边界或 JSON 字段断言的需求，生成测试计划。
4. 提交完整 workflow job，查看计划生成、工具执行、报告汇总、失败原因分类和修复建议。
5. 运行发布检查或真实 LLM strict eval，验证这条链路不是只靠页面演示，而是可重复回归。

## 快速启动

以下命令默认在项目根目录执行。

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env.runtime
```

编辑 `.env.runtime`，至少替换 `APP_API_KEY` 或 `APP_API_KEYS`，并替换 `ZHIPU_API_KEY`，不要提交真实密钥。

启动后端：

```bash
./.venv/bin/python scripts/run_server.py --host 127.0.0.1 --port 8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

启动前端工作台：

```bash
cd frontend
npm install --ignore-scripts --omit=optional
npm run dev
```

前端地址：

```text
http://127.0.0.1:5173
```

## 常用能力

- `POST /api/v1/test-cases/generate`：同步生成测试用例。
- `POST /api/v1/test-cases/generation-jobs`：提交异步生成任务。
- `GET /api/v1/test-cases/generation-jobs/{job_id}`：查询任务详情。
- `POST /api/v1/test-cases/export`：导出 Excel。
- `POST /api/v1/test-cases/export/pytest`：导出 pytest 模板或登录 API adapter 示例。
- `POST /api/v1/evaluation/coverage`：评估需求覆盖率。
- `POST /api/v1/evaluation/coverage/gaps/knowledge`：把人工确认的覆盖缺口沉淀到知识库。
- `POST /api/v1/knowledge/ingest`：导入知识库文档。
- `GET /api/v1/generation-records`：查询生成历史。
- `GET /api/v1/generation-gates`：查询待处理门控记录。
- `GET /api/v1/operations/metrics`：查询内部运行指标 JSON。
- `GET /api/v1/operations/metrics/prometheus`：查询 Prometheus 文本指标。

完整接口、请求示例、配置项和工作流说明见 [项目详细说明](docs/project-guide.md)。

## 依赖清单

- `requirements.txt`：统一后端安装入口，包含 API、worker、RAG、MySQL backend、测试和 lint 所需依赖。
- `constraints.txt`：关键依赖上界约束，用于降低 CI 和镜像构建时的版本漂移风险；它不是完整 lock 文件。

语义 embedding 依赖体积较大，不进入默认安装。需要 `EMBEDDING_PROVIDER=sentence_transformers` 时，按 [部署说明](docs/deployment.md) 的可选安装命令单独安装。

## 知识库

导入仓库内置示例知识库：

```bash
./.venv/bin/python scripts/ingest_documents.py knowledge --recursive --reset
```

如果本地存在私有导出知识库 `knowledge_export/`，可一起导入：

```bash
./.venv/bin/python scripts/ingest_documents.py knowledge knowledge_export --recursive --reset
```

`knowledge_export/`、`.env.runtime`、模型缓存、向量库和运行日志都不应提交。

## 异步任务

本机 Python 直连 Docker Redis 时使用：

```bash
GENERATION_JOB_QUEUE_BACKEND=rq REDIS_URL=redis://127.0.0.1:6379/0 ./.venv/bin/python scripts/run_generation_worker.py
```

Docker Compose 容器内部使用 `REDIS_URL=redis://redis:6379/0`。完整本机运行步骤见 [本机运行](docs/local-run.md)。

## 发布检查

提交前运行：

```bash
./.venv/bin/python scripts/run_release_checks.py
```

该命令默认执行登录和订单退款 RAG 固定评估、核心 pytest 回归、测试 Agent 契约模块 mypy 类型检查、测试计划固定评估、内部 readiness 检查、异步任务 stale 恢复 smoke、队列观测检查和 `git diff --check`，不会调用真实 LLM。需要真实 LangGraph + RAG + LLM + 质量门控 smoke 时，显式加 `--include-llm-smoke`。

Python lint：

```bash
./.venv/bin/python -m ruff check app scripts tests
```

前端本地检查：

```bash
cd frontend
npm test
npm run build
```

也可以在已安装前端依赖后使用统一入口：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-frontend-check
```
