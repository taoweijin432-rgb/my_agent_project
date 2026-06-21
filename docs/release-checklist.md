# 封版检查清单

建议封版标签：`v0.2-async-hitl-baseline`

封版目标：形成一个可演示、可集成、可放入 GitHub 仓库、可用于简历讲解的 RAG Agent 后端基线版本。该版本不是公网多租户生产最终态，后续升级重点是外部队列、生产数据库、真实 Agent 框架和可观测性。

## 1. 封版范围

本次封版包含：

- FastAPI REST API。
- 智谱 LLM JSON Mode 调用封装。
- Chroma RAG 知识库导入、查询、文档 upsert/delete。
- 轻量 Agent workflow：需求分析、知识检索、召回不足 query rewrite、测试策略规划、Prompt 构造、LLM 生成、Schema 校验、后处理、Reviewer、门控、usage 估算。
- `GenerationWorkflowState` 短期记忆和 `workflow_steps` 节点轨迹。
- Reviewer Agent 本地质量审查和可选重试。
- 预算门控、质量门控和结构化 human-in-the-loop 响应。
- 门控事件持久化、待处理查询和人工审批/驳回闭环。
- 生成历史 SQLite 持久化、详情回放和质量报告。
- 异步生成任务队列、worker 并发控制和队列满 429 背压。
- API key、CORS、应用内限流、请求 ID、耗时响应头、生产启动配置校验。
- Dockerfile、Docker Compose 模板、运行配置示例和部署说明。
- 项目说明、Agent 架构说明、RAG 评估说明、问题跟踪文档。

## 2. 封版前必须验证

代码验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

敏感信息扫描：

- 扫描真实服务 key、模型 key、云厂商 key 和 `.env/config.py` 泄漏。
- 扫描范围覆盖 `.github`、示例环境文件、`app/`、`docs/`、`scripts/`、`tests/`、`README.md`、Docker 文件和依赖文件。
- 不在文档中固化具体 key pattern，避免封版文档本身被扫描命令误报。

当前允许的已知命中：

- `tests\test_deployment_templates.py` 中的敏感片段断言。
- `tests\fixtures\rag_eval_cases.json` 中的业务 fixture 文本。

运行环境检查：

- `.env/config.py` 不提交。
- `.env.runtime` 不提交。
- `.venv/`、`.model_cache/`、`data/`、`logs/`、`knowledge_export/` 不提交。
- 真实 API key 不进入 README、docs、tests、示例配置或提交记录。

## 3. 封版验收标准

功能验收：

- `/health` 可返回服务状态。
- 同步生成接口仍可按原接口返回 `GenerateResponse`。
- 异步生成接口可返回 `job_id`，并可查询 `queued/running/succeeded/failed` 状态。
- RAG 文档可导入、查询、upsert、delete。
- 生成历史可查询列表和详情。
- 预算/质量门控失败可写入待处理列表。
- 门控记录可被 `approved` 或 `rejected`，重复处理返回 409。
- Excel 导出仍可用。

工程验收：

- 全量测试通过。
- 文档能解释项目定位、架构、配置、部署和升级路线。
- 问题清单保留已修复项和剩余风险。
- Git 工作区干净。

## 4. 已知限制

- 异步队列是进程内实现，不适合多进程或多实例共享任务状态。
- SQLite 适合单机和受控部署，不适合作为高并发多租户生产数据库。
- 应用内限流是内存级限流，不能替代网关层限流。
- 当前 Reviewer 主要是本地规则，不是大模型评审。
- RAG 尚未接入 rerank、metadata filter 的完整查询策略和线上召回监控。
- 当前没有用户体系、项目级权限隔离、RBAC 和多知识库授权。
- 没有集中日志、metrics、告警和分布式链路追踪。
- Docker 运行模板已提供，但当前机器未完成 Docker 实机验证。

## 5. 不纳入本次封版

- Redis/Celery/RQ 外部队列。
- PostgreSQL 数据库迁移。
- LangGraph 真实框架迁移。
- 多用户权限系统。
- 前端管理后台。
- 与禅道、TestRail、飞书多维表格等平台的正式 adapter。
- 公网 HTTPS 网关、WAF、集中监控和告警。

## 6. 封版后第一批升级

推荐顺序：

1. 外部队列：将 `InMemoryGenerationJobQueue` 替换为 Redis + RQ 或 Celery。
2. 生产数据库：将生成历史、任务状态、门控审批从 SQLite 迁移到 PostgreSQL。
3. Agent 框架：将 `WorkflowNode` 和 `GenerationWorkflowState` 映射到 LangGraph。
4. RAG 增强：增加 metadata filter、rerank、固定评估集和召回指标。
5. 可观测性：增加结构化日志、metrics、队列长度、失败率、LLM 成本和告警。
6. 权限隔离：增加用户、项目、知识库权限和操作审计。
