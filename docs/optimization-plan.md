# 项目优化计划

本文记录项目从当前可交付状态继续工程化、生产化的推进计划。原则是先补低风险工程基线，再逐步处理运行边界和质量治理。

当前整体评估见 [project-assessment.md](project-assessment.md)。本计划中的本地交付目标已基本完成，后续重点转向生产运行治理、权限边界和 RAG 质量深化。

当前所处阶段：

- 工程基线、前端可维护性和功能落地增强已完成主要目标。
- 生产运行边界处于收尾阶段，Redis/RQ + MySQL 的长时、多轮、多 worker 稳定性验证和测试 Agent workflow job 的 Docker/RQ + MySQL 实机 smoke 已具备可选演练入口；测试 Agent workflow 已新增耗时观测字段、真实 LLM attempt 级调用 metrics、错误分类 retry/backoff、阶段失败码、真实 LLM benchmark 入口、JSONL 历史记录、strict 测评模式、eval summary 汇总、前端详情展示、worker 吞吐 summary、吞吐阈值门禁、报告摘要事实门禁、报告原因分类门禁、原因感知建议门禁、报告建议 grounding 门禁、next-action 质量门禁和证据 artifact/output 可追溯性门禁。HTTP adapter 已支持声明式 `json_assertions`，可在状态码通过时继续校验响应 JSON 字段。真实 LLM workflow eval 已支持按 `--case-id`/`--case-slice` 分批和 `--case-delay-seconds` 串行限速，429 会作为 `rate_limited` 进入可重试错误分类。2026-07-15 使用当前默认模型 `glm-4-flash` 完成当前 15 条需求到报告样本的真实 LLM strict 覆盖：原 11 条全量 strict eval 与新增 4 条真实业务样本分批 strict eval 均为 `case_pass_rate=1.0`，所有质量门禁为 1.0，无 fallback、无 retry、无 timeout/429；新增 4 条在 `json_assertions` 新契约下 `plan_generation.avg=29567.073ms`、`max=35863.873ms`。这说明当前模型下输出契约和耗时都可控，之前长耗时问题应按模型/上游差异处理。默认 deterministic workflow eval 已扩展到 15 条样本，覆盖 HTTP、pytest、SQL adapter 缺失、manual skipped、422 参数校验失败、金额不一致、异步终态不一致、前置失败和回调幂等冲突，其中金额不一致和异步终态不一致已通过 JSON 字段断言表达，但 deterministic 路径只作为快速回归保护，不作为模型约束效果结论。当前重点转向更多真实业务样本、真实模型强门禁常态化和生产监控接入。
- RAG 质量治理已具备固定评估入口，后续要扩大真实业务样本和失败归因维度。

后续路线：

1. 扩展 Redis/RQ + MySQL 稳定性收尾：现有多轮提交、多 worker 并行、每轮队列 alert 断言、MySQL/RQ 状态一致性检查已覆盖测试计划执行 job 和测试 Agent workflow job；后续增加更长时长、更高并发和异常恢复组合演练。
2. 扩充测试 Agent 真实业务执行样本：把需求、计划、工具执行、报告和评估集连成可重复验证链路。已推进：执行测评集新增退款多步骤业务流和 HTTP header 权限阻塞样本，并将 blocked grounding 纳入默认执行评估门禁；`scripts/evaluate_test_agent_workflow.py` 从需求样本串起规则 planner、工具执行和报告评估，当前覆盖退款失败审计、权限/鉴权失败、异步队列状态超时、支付对账幂等冲突、库存预占锁定异常、通知重试失败、文件导出越权下载、用户资料参数校验失败、退款金额不一致、异步终态不一致、结账前置失败、支付回调幂等冲突、pytest 断言失败、SQL adapter 缺失和人工确认未执行 15 条 workflow；报告和 workflow eval 已新增 `summary_fact_quality_rate`、`reason_classification_rate`、`reason_aware_recommendation_rate`、`recommendation_grounding_rate`、`next_action_quality_rate` 和 `evidence_artifact_quality_rate`，要求报告摘要反映状态/执行数/覆盖率/状态计数，failed/blocked/skipped 报告具备结构化原因分类、建议落到具体 step、包含明确动作关键词，并能追溯到 artifact 路径或 output summary。原因分类已覆盖 HTTP timeout、permission denied、permission not enforced、conflict、upstream unavailable、validation_error、response_assertion_mismatch、pytest assertion mismatch、adapter missing 和 manual confirmation required，并能驱动差异化建议。生产接口已新增 `POST /api/v1/test-agent/workflow-jobs`，把真实 LLM 计划生成、工具执行和报告汇总放入后台 job；前端测试计划工作台已支持提交 workflow job、查看列表/详情、轮询活跃任务并把 `result.plan`/`result.report` 回填到页面。
3. 评估 MySQL 是否切为默认 backend：连接超时和短连接运行边界已补齐；必须先完成长时运行、高并发和恢复演练，再根据压测结果决定是否引入连接池，不直接用当前 smoke 结论替代生产容量评估。
4. 深化 RAG/Agent 质量治理：按业务域补充召回失败样本、关键词/来源命中率、真实 LLM planner 质量门禁和报告内容质量门禁。当前 test plan eval 和 workflow eval 均已提供真实 LLM 入口，workflow eval 已输出失败诊断 code 并预校验 `tool_args` schema，release checklist 已补 dry-run 模板；LLM planner 已增加 HTTP tool args 契约归一化、header 安全白名单和结构化需求优先的 `test_types` 收敛，真实模型输出会被转换为真实 adapter 可执行的 `TestPlan` 后再评估。真实 LLM workflow eval 已支持 `--concurrency`、`--case-id`、`--case-slice`、`--case-delay-seconds`，以及 `--use-cache`/`--refresh-cache` 复用或刷新真实模型历史输出。deterministic 路径只作为快速回归保护，不推荐用于判断模型约束效果；模型质量结论以真实 LLM strict workflow eval 为准，模型切换后必须重新跑真实 strict eval 并记录 benchmark history。
5. 补齐生产权限和运维边界：API key 轮换、最小权限说明、日志/指标接入正式监控系统。

## 阶段 1：工程验证基线

状态：已完成。

目标：

- 后端发布检查继续作为默认质量基线。
- 前端构建进入 CI。
- Python lint 进入 CI。
- Python 依赖增加上界约束，降低 CI 和镜像构建时的版本漂移风险。

已落地：

- GitHub Actions 新增前端 `npm test` 和 `npm run build`。
- GitHub Actions 新增 `python -m ruff check app scripts tests`。
- 新增 `constraints.txt`，并将后端依赖统一收敛到 `requirements.txt`。
- Docker 构建路径复制 `constraints.txt`。
- API 路由、导出和中间件测试已移除 FastAPI `TestClient` 依赖，改为直接路由调用、核心服务验证或 `httpx.ASGITransport` 异步端点验证，避免沙箱环境阻塞。

验收命令：

```bash
./.venv/bin/python scripts/run_release_checks.py
cd frontend && npm test && npm run build
```

## 阶段 2：前端可维护性

状态：基本完成，剩余为测试扩展和可选 layout 拆分。

目标：

- 逐步拆分 `frontend/src/App.tsx`，优先抽离稳定、可测试的纯逻辑。
- 为 API client、配置持久化和关键页面交互补测试。

已落地：

- 抽出 `frontend/src/api/settings.ts`。
- 抽出 `frontend/src/api/client.ts` 的 URL 拼接、health URL、query string 和错误消息归一化辅助函数。
- 抽出 `frontend/src/api/download.ts`，统一 Blob 下载逻辑。
- 抽出 `frontend/src/api/generate.ts`，统一生成请求归一化逻辑。
- 抽出 `frontend/src/api/requirements.ts`，统一需求点文本解析和标签拆分逻辑。
- 抽出 `frontend/src/api/format.ts`，统一日期、耗时、百分比和状态/类型标签展示格式化。
- 拆出 `frontend/src/components/GeneratePanel.tsx`，独立承载用例生成表单、同步生成和异步任务提交。
- 拆出 `frontend/src/components/JobsPanel.tsx`，独立承载异步任务列表、状态过滤、任务详情和结果回填。
- 拆出 `frontend/src/components/KnowledgePanel.tsx`，独立承载知识文档列表、upsert/delete 和检索验证。
- 拆出 `frontend/src/components/HistoryPanel.tsx`，独立承载生成历史、门控列表、详情查看和审批处理。
- 拆出 `frontend/src/components/CoveragePanel.tsx`，独立承载需求覆盖率输入、评估调用和结果展示。
- 拆出 `frontend/src/components/ResultView.tsx`，复用生成结果、导出入口和检索上下文展示。
- 拆出 `frontend/src/components/common.tsx`，复用状态徽标、指标、空状态、提示条、标签列表和片段列表等小组件。
- 新增 Vitest 配置、配置持久化单测、API client 辅助函数单测、下载工具单测、生成请求归一化单测、需求解析单测和格式化单测。
- 新增 `frontend/src/components/panel-behavior.test.tsx`，覆盖异步任务详情回填、门控审批、知识库保存/删除/检索。
- 扩展 `frontend/src/components/panel-behavior.test.tsx`，覆盖同步生成、异步任务提交、结果导出、覆盖率错误提示和覆盖率结果展示。

下一步：

- 评估是否把 `App.tsx` 的连接配置栏、侧边导航抽成 layout 组件；如果继续拆，优先保证测试覆盖和文件边界清晰。
- 如果不继续做前端可选拆分，可回到阶段 3 的生产运行边界或阶段 4 的 RAG 质量治理。

## 阶段 3：生产运行边界

状态：部分完成。

目标：

- 明确 SQLite、MySQL、Redis/RQ 在不同部署规模下的使用边界。
- 增强 worker crash、Redis 短暂不可用、MySQL 短暂不可用时的恢复验证。
- 补充可观测性：结构化日志、关键计数指标、队列积压和失败告警。
- 增强鉴权：多 API key、key 轮换、最小权限或网关集成说明。

建议顺序：

1. 增加 MySQL/RQ 故障恢复 smoke 文档和手动演练脚本。已完成：`scripts/smoke_recover_stale_generation_jobs.py`，默认使用临时 SQLite，并支持 `--backend mysql`。
2. 将请求日志改为结构化 JSON 可选输出。已完成：`REQUEST_LOG_FORMAT=text|json`。
3. 增加 `/ready` 或只面向内部的运行状态检查脚本。已完成：`GET /ready` 和 `scripts/check_readiness.py` 复用同一套检查。
4. 支持 `APP_API_KEYS` 多 key 配置，并保留 `APP_API_KEY` 兼容。已完成。
5. 增加队列/数据库观测脚本并接入发布检查。已完成：`scripts/check_generation_queue.py --json --fail-on-mismatch` 会输出生成任务状态计数、RQ registry/worker 快照和健康判断；`scripts/check_test_plan_execution_queue.py --json --fail-on-mismatch` 会按 job function 过滤共享 RQ 队列中的测试计划执行任务；`scripts/smoke_test_plan_execution_worker.py` 验证测试计划执行 worker 的多 job 稳定性和 stale 恢复。
6. 增加 Redis/MySQL 短暂不可用恢复演练。已完成：`scripts/smoke_runtime_dependency_outage.py` 会短暂停止 Redis/MySQL，验证队列检查失败到明确错误，再恢复服务并验证检查通过；该脚本为显式可选 smoke，不进入默认 CI。
7. 增加 Redis/RQ worker 稳定性演练。已完成：`scripts/smoke_rq_mysql_worker_stability.py` 会在 MySQL profile 环境中启动临时 worker，提交多条测试计划执行 job，校验 passed/failed 报告混合结果和执行 artifact；该脚本为显式可选 smoke，不进入默认 CI。`DATABASE_BACKEND=mysql` 时，测试计划执行 job 状态写入 MySQL `test_plan_execution_jobs` 表。
8. 增加队列 metrics/alert 阈值检查。已完成：`scripts/check_queue_alerts.py` 会聚合生成队列和测试计划执行队列的 `metrics`/`alerts`，支持 active jobs、RQ queued/started/failed、worker heartbeat 和 require-worker 阈值；`scripts/run_release_checks.py --include-queue-alert-check` 可显式触发。
9. 增加长时稳定性演练入口。已完成：`scripts/smoke_rq_mysql_worker_stability.py` 支持 `--rounds`、`--jobs-per-round` 和 `--worker-count`，每轮执行后都会检查测试计划执行队列 alert，输出总 job 数、每轮耗时、总耗时、报告状态、artifact 数和 worker 数。长时间实机压测仍作为人工可选步骤，不进入默认 CI。
10. 将真实 LLM 的需求到报告生产调用异步化。已完成：新增测试 Agent workflow job，支持 `POST /api/v1/test-agent/workflow-jobs` 提交、列表和详情查询；job 复用现有 `GENERATION_JOB_QUEUE_BACKEND=in_memory|rq`、Redis/RQ worker、SQLite/MySQL 持久化、stale running 恢复和队列满背压。已新增 `scripts/check_test_agent_workflow_queue.py` 并接入 queue alert 聚合和默认发布检查；前端 `TestPlanPanel` 已支持提交完整 workflow、查看列表/详情、轮询活跃任务和回填结果。`scripts/smoke_test_agent_workflow_rq_mysql.py` 已完成 Docker/RQ + MySQL 实机 smoke，验证真实 API、Redis、MySQL、RQ worker、HTTP adapter、artifact、报告和队列 alert。首批耗时观测已完成：`result.timing` 记录计划生成、工具执行和报告汇总阶段，`job.timing` 派生排队耗时、任务运行耗时和 workflow 阶段耗时，workflow eval/smoke 输出耗时汇总。阶段失败分层已完成：阶段异常会写入 `error.stage`、阶段失败码和 partial timing，例如 `plan_generation_timeout`。真实 LLM benchmark 已完成入口和 JSONL 历史记录：`--include-llm-workflow-benchmark` 会运行真实模型调用并把 summary 追加写入 `data/llm-workflow-benchmark-history.jsonl`。后续重点不是增加离线测评权重，而是补真实 LLM strict 门禁常态化、模型切换对比、重试策略和 worker 处理能力观测。

## 阶段 4：RAG 质量治理

状态：部分完成。

目标：

- 扩展登录模块之外的固定评估集。
- 增加召回失败样本沉淀机制。
- 评估 metadata filter、rerank 或 hybrid search 的收益。
- 明确 hash embedding 只用于本地/CI 验证，生产默认使用语义 embedding。

建议顺序：

1. 新增一个非登录模块的 `rag_eval_cases.json`。已完成：订单退款模块知识库、`tests/fixtures/refund_rag_eval_cases.json` 和默认发布检查接入。
2. 扩展 `scripts/evaluate_rag.py` 输出 per-source 命中统计。已完成：`summary.source_stats`。
3. 为低命中 case 生成可追加到知识库的缺口报告。已完成：`scripts/evaluate_rag.py --gap-report`。

## 阶段 5：功能落地增强

状态：基本完成，后续为更多业务 adapter 和固定评估集回流扩展。

目标：

- 将 pytest 导出从模板能力推进到至少一个可执行 adapter。
- 建立人工覆盖确认回流机制。
- 让生成历史和覆盖率评估形成闭环。

建议顺序：

1. 先实现登录 API 的可执行 pytest adapter 示例。已完成：`PytestExportRequest.adapter=login_api` 和对应导出单测。
2. 支持把人工确认的缺口写入知识库或评估集。已完成：新增覆盖缺口知识库沉淀接口，前端覆盖率页支持确认后 upsert 到知识库。
3. 在前端历史页展示覆盖率报告入口。已完成：历史详情可一键带入用例并切换到覆盖率页。
