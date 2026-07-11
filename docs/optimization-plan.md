# 项目优化计划

本文记录项目从当前可交付状态继续工程化、生产化的推进计划。原则是先补低风险工程基线，再逐步处理运行边界和质量治理。

当前整体评估见 [project-assessment.md](project-assessment.md)。本计划中的本地交付目标已基本完成，后续重点转向生产运行治理、权限边界和 RAG 质量深化。

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
5. 增加队列/数据库观测脚本并接入发布检查。已完成：`scripts/check_generation_queue.py --json --fail-on-mismatch` 会输出任务状态计数、RQ registry/worker 快照和健康判断；默认发布检查使用临时 SQLite/in-memory 配置做轻量验证。

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
