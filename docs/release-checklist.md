# 发布检查清单

建议发布标签：`v0.2-async-hitl-baseline`

发布目标：形成一个可运行、可集成、可发布的 RAG Agent 后端基线版本，并提供轻量前端工作台用于本地操作和演示。该版本不是公网多租户生产最终态，后续升级重点是生产数据库、队列治理、Agent 框架、前端后台和可观测性。

## 1. 发布范围

本次发布包含：

- FastAPI REST API。
- 智谱 LLM JSON Mode 调用封装。
- Chroma RAG 知识库导入、查询、文档 upsert/delete。
- 轻量 Agent workflow：需求分析、知识检索、召回不足 query rewrite、测试策略规划、Prompt 构造、LLM 生成、Schema 校验、后处理、Reviewer、门控、usage 估算。
- `GenerationWorkflowState` 短期记忆和 `workflow_steps` 节点轨迹。
- Reviewer Agent 本地质量审查和可选重试。
- 预算门控、质量门控和结构化 human-in-the-loop 响应。
- 门控事件持久化、待处理查询和人工审批/驳回闭环。
- 生成历史数据库持久化、详情回放和质量报告。
- 需求覆盖率评估接口、缺口报告和人工确认后知识库沉淀接口。
- Excel 导出和 pytest 自动化模板导出。
- 登录场景效率对比脚本和报告。
- 异步生成任务队列、Redis/RQ 外部队列、worker 进程和队列满 429 背压。
- 默认 LangGraph workflow backend，`local` backend 保留为 fallback 和行为对照。
- API key、CORS、应用内限流、请求 ID、耗时响应头、生产启动配置校验。
- Dockerfile、Docker Compose 模板、运行配置示例和部署说明。
- React + Vite 前端工作台，覆盖生成、异步任务、知识库、历史、门控和覆盖率评估的操作入口。
- 项目说明、Agent 架构说明、RAG 评估说明和部署文档。

## 2. 发布前必须验证

代码验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

推荐使用统一发布检查入口：

```bash
./.venv/bin/python scripts/run_release_checks.py
```

该入口默认执行：

- 隔离登录知识库导入。
- 隔离订单退款知识库导入。
- 登录和订单退款 RAG 固定评估，要求 source hit 和 keyword hit 均为 100%。
- 核心 pytest 回归，包括 API 路由、导出、知识库和中间件测试；这些测试不依赖 FastAPI `TestClient`，适合沙箱环境运行。
- 测试 Agent 契约模块 mypy 类型检查，覆盖测试计划模型、工具 adapter、执行编排、执行 job、store、报告和 RQ worker。
- 测试计划生成固定评估，验证工具选择、测试类型和风险关键词命中率。
- 异步任务 stale 恢复 smoke，验证过期 `running` 任务会失败且 fresh 任务不被误杀。
- 内部 readiness 检查，验证运行目录、数据库任务状态库和队列依赖。
- 生成队列观测检查，输出数据库任务状态统计、队列快照和健康判断，默认使用临时 SQLite/in-memory 配置避免污染本地数据。
- `git diff --check`。

前端验证：

```bash
cd frontend
npm test
npm run build
```

如需执行真实 LLM 强门控 smoke，显式增加：

```bash
./.venv/bin/python scripts/run_release_checks.py --include-llm-smoke
```

该模式会启动本地 FastAPI 服务并调用真实模型，验证不达标请求返回 `quality_gate_failed` 409、达标请求返回 200。它会消耗模型额度，不建议放入默认 CI。

CI 验证：

- `.github/workflows/ci.yml` 会在 push 和 pull request 时运行 `scripts/run_release_checks.py`。
- `.github/workflows/ci.yml` 的 `frontend-build` job 会运行 `npm test` 和 `npm run build`。
- 真实 LLM smoke 保留为 `workflow_dispatch` 手动触发，需勾选 `run_llm_smoke` 并配置 GitHub Secret：`ZHIPU_API_KEY`。
- 不把真实 API key 写入 workflow 文件、README 或示例配置。

敏感信息扫描：

- 扫描真实服务 key、模型 key、云厂商 key 和 `.env/config.py` 泄漏。
- 扫描范围覆盖 `.github`、示例环境文件、`app/`、`docs/`、`scripts/`、`tests/`、`README.md`、Docker 文件和依赖文件。
- 不在文档中固化具体 key pattern，避免发布文档本身被扫描命令误报。

当前允许的已知命中：

- `tests\test_deployment_templates.py` 中的敏感片段断言。
- `tests\fixtures\rag_eval_cases.json`、`tests\fixtures\login_rag_eval_cases.json` 和 `tests\fixtures\refund_rag_eval_cases.json` 中的业务 fixture 文本。

运行环境检查：

- `.env/config.py` 不提交。
- `.env.runtime` 不提交。
- `.venv/`、`.model_cache/`、`data/`、`logs/`、`knowledge_export/` 不提交。
- 真实 API key 不进入 README、docs、tests、示例配置或提交记录。

## 3. 发布验收标准

功能验收：

- `/health` 可返回服务状态。
- `/ready` 或 `scripts/check_readiness.py` 可返回 ready。
- 同步生成接口仍可按原接口返回 `GenerateResponse`。
- 异步生成接口可返回 `job_id`，并可查询 `queued/running/succeeded/failed` 状态。
- RAG 文档可导入、查询、upsert、delete。
- 生成历史可查询列表和详情。
- 预算/质量门控失败可写入待处理列表。
- 门控记录可被 `approved` 或 `rejected`，重复处理返回 409。
- Excel 导出仍可用。
- pytest 导出可生成默认 skip 的自动化脚手架，也可生成登录 API adapter 示例。
- 覆盖率评估可返回未覆盖需求、缺失关键词和建议，并可把人工确认的缺口 upsert 到知识库。

工程验收：

- 全量测试通过。
- 测试 Agent 契约模块 mypy 类型检查通过。
- 前端 Vitest 和 Vite 构建通过。
- 文档能解释项目定位、架构、配置、部署和后续工作。
- 已知限制和后续工作有明确说明。
- Git 工作区干净。

## 4. 已知限制

- Redis/RQ 外部队列已接入；任务状态和生成历史写入当前数据库 backend。
- 默认 SQLite 适合单机和受控部署，不适合作为高并发多租户生产数据库；MySQL backend 已实现并通过 smoke，但尚未切为生产默认。
- 应用内限流是内存级限流，不能替代网关层限流。
- 当前 Reviewer 主要是本地规则，不是大模型评审。
- 当前需求覆盖率评估主要基于关键词匹配，适合作为缺口初筛；缺口沉淀需要人工确认，不替代需求评审。
- pytest 导出默认仍是模板能力；当前已提供登录 API adapter 示例，其他业务 API 或 UI adapter 仍需按项目补充。
- RAG 尚未接入 rerank、metadata filter 的完整查询策略和线上召回监控。
- 当前没有用户体系、项目级权限隔离、RBAC 和多知识库授权。
- 没有集中日志、metrics、告警和分布式链路追踪。
- Docker 轻量 Redis/RQ smoke 已完成实机验证；完整 ML/RAG 镜像仍需要在网络稳定环境做生产构建验证。
- LangGraph backend 已完成最小服务级 smoke，并已切为默认 backend；`local` backend 仍可通过配置回退。

## 5. 不纳入本次发布

- Celery 或更严格的原子有界队列实现。
- 将 MySQL 切为默认数据库 backend。
- MySQL 备份恢复、Compose 服务模板、更长时间稳定性和高并发验证。
- 深化 LangGraph checkpoint、interrupt、人审节点和 trace 能力。
- LangGraph checkpoint、interrupt、人审节点和可视化 trace 深度集成。
- 多用户权限系统。
- 生产级前端管理后台，包括多项目、多用户、权限和审计。
- 与禅道、TestRail、飞书多维表格等平台的正式 adapter。
- 公网 HTTPS 网关、WAF、集中监控和告警。

## 6. 后续工作

推荐顺序：

1. 生产数据库：补齐 MySQL Compose 服务模板、备份恢复、连接池参数、稳定性验证，并评估是否切为默认 backend。
2. Docker 生产硬化：完整 ML/RAG 镜像构建验证、非 root bind mount 权限说明、镜像体积和缓存策略。
3. Agent 框架：在默认 LangGraph backend 上补齐 checkpoint、interrupt、人审节点和 trace 能力，并保留 `local` 回滚策略。
4. RAG 增强：增加 metadata filter、rerank、固定评估集和召回指标。
5. 可观测性：增加结构化日志、metrics、队列长度、失败率、LLM 成本和告警。
6. 权限隔离：增加用户、项目、知识库权限和操作审计。
7. 测试落地：继续扩展退款等业务 API adapter，并把人工覆盖确认结果回流到固定评估集。
