# 项目当前评估

评估日期：2026-07-18

## 1. 总体结论

当前项目已经从原型推进到可交付的工程基线：后端 API、RAG、Agent workflow、异步任务、历史持久化、门控审批、覆盖率评估、前端工作台、Docker/Compose、发布检查和核心文档都已形成闭环。

适合定位：

- 个人或小团队本地使用。
- 内部演示、试点和受控环境部署。
- 作为 RAG Agent 测试用例生成系统的可扩展基线。

不适合直接定位：

- 公网多租户 SaaS。
- 高并发生产系统。
- 带完整用户、权限、审计、计费和集中运维体系的企业平台。

判断：项目当前不是“只完成 demo”，而是已经具备工程交付能力；剩余工作主要集中在生产级治理、权限隔离、可观测性和 RAG 质量深化。

## 2. 已完成能力

后端能力：

- FastAPI REST API 已覆盖同步生成、异步生成、任务查询、历史查询、门控处理、知识库管理、覆盖率评估、Excel 导出和 pytest 导出。
- Agent workflow 已覆盖需求分析、知识检索、query rewrite、策略规划、Prompt 构造、LLM 调用、Schema 校验、Reviewer、门控、usage 估算和历史落库。
- LangGraph backend 已作为默认 workflow backend，`local` backend 保留为回退路径。
- Redis/RQ 外部队列和 in-memory 队列都已支持，队列满时返回 429 背压。
- SQLite 和 MySQL backend 都已实现，MySQL 初始化、备份、恢复和 smoke 文档齐备。

质量和验证：

- 默认发布检查覆盖 RAG 固定评估、核心 pytest、测试 Agent 契约模块 mypy 类型检查、stale job 恢复、监控 metrics/alert 模板验证、readiness、队列观测、运行结果脱敏回归、服务模式负载 smoke 单测和 `git diff --check`。
- 测试 Agent workflow 已具备真实 LLM strict workflow eval：2026-07-15 当前默认模型 `glm-4-flash` 已覆盖当前 15 条需求到报告样本，原 11 条全量 strict eval 与新增 4 条在 `json_assertions` 新契约下分批 strict eval 均通过，所有质量门禁为 1.0，无 fallback、无 retry、无 timeout/429；模型质量结论以该真实路径为准。
- API 路由、导出和中间件测试已移除 FastAPI `TestClient` 依赖，适合沙箱环境运行。
- 前端已接入 Vitest，覆盖配置、API client、下载、生成请求、需求解析、格式化和关键面板行为。
- Python 依赖已收敛到统一 `requirements.txt`，版本边界由 `constraints.txt` 管理。

前端和体验：

- React + Vite 工作台已覆盖生成、异步任务、知识库、历史、门控审批和覆盖率评估。
- `App.tsx` 已拆出主要业务面板和公共组件，维护成本明显低于单文件巨型组件。

文档和部署：

- README、项目指南、架构基线、Agent 架构、部署、本机运行、MySQL 运维、RAG 评估、发布清单和优化计划已形成文档矩阵。
- Dockerfile、统一 `docker-compose.yml`、`.env.example` 和发布检查入口已完成整合。

## 3. 主要优势

- 工程闭环完整：生成、审查、门控、持久化、导出、前端操作和发布检查都能串起来。
- 风险边界清楚：文档明确区分本地、受控部署和生产化缺口。
- 测试策略务实：高风险后端逻辑、导出、队列、RAG 评估、真实 LLM workflow strict 门禁和前端核心交互都有覆盖。
- 可演进性较好：存储、队列、workflow backend、RAG 评估和导出 adapter 都保留了扩展点。
- 沙箱适配更稳：测试不再依赖容易卡住的 `TestClient` 路径。

## 4. 关键缺口

### 4.1 真实敏感数据和密钥治理

运行结果统一脱敏已经完成：共享 redaction 工具覆盖 artifact、`ToolRun.output_summary`、HTTP JSON assertion 失败信息、pytest 输出摘要、报告 evidence、Markdown/JSON 导出、API 返回、历史记录和异常日志，回归测试已纳入默认发布检查。

剩余风险不再是应用内输出脱敏闭环，而是生产数据治理：真实密钥托管、生产样本准入、敏感数据分级、删除审计、备份介质保护和发布前 secret scanning 仍需制度化。

### 4.2 权限和租户隔离

当前只有 API key 级别的保护，缺少用户体系、项目级权限、知识库隔离、历史记录隔离、RBAC 和操作审计。受控内网可接受，公网或多团队共享环境不可接受。

### 4.3 集中可观测性

当前已有结构化请求日志、readiness、队列观测脚本、内部 metrics JSON/Prometheus 输出、Prometheus 告警规则模板、Prometheus/Alertmanager 示例配置和离线 metrics/alert 模板验证，但还没有集中日志采集、真实 Prometheus 抓取、正式告警落地和分布式链路追踪。

### 4.4 真实 LLM 质量趋势

当前真实 LLM strict workflow eval 已能约束模型输出，但样本规模仍偏小，且模型耗时、timeout、retry 和上游限流会随模型切换变化。deterministic/offline eval 只能做快速回归，不推荐用于判断真实模型约束效果；后续需要把真实 LLM benchmark history 作为模型切换和发布前判断依据。

### 4.5 RAG 质量深化

固定评估集已扩展到登录和退款模块，并支持低命中 gap report，但还缺 metadata filter、rerank、hybrid search、线上召回监控和更大规模评估集。知识库增长后，召回质量可能随文档结构、metadata、chunk 策略和业务域变化而漂移。

### 4.6 生产数据库和队列稳定性

MySQL 与 Redis/RQ 已具备可操作基线，但默认仍是 SQLite/in-memory。Redis/MySQL 短暂不可用演练、队列告警阈值、测试计划执行 job MySQL 持久化、测试 Agent workflow MySQL/RQ service-mode smoke、12 job 多轮负载 smoke 和 MySQL 连接超时参数已补齐；真正生产化前还需要更长时长稳定性、备份恢复定期验证、连接池取舍和容量评估。

### 4.7 队列一致性和失败恢复

queued/running stale 恢复已经覆盖测试计划执行和测试 Agent workflow，但真实生产还会遇到 worker 被 kill、Redis 短暂不可用、MySQL 连接闪断、RQ registry 残留、重复 job id、任务执行中进程退出等组合场景。已有 smoke 入口，仍需要定期实机演练和记录结果。

### 4.8 前端产品化

当前前端是工作台，不是完整管理后台。多项目、多用户、权限、审计、批量操作和团队协作仍未实现。

### 4.9 部署安全边界

应用内已有 API key、CORS、rate limit、生产配置校验、HTTP base URL allowlist 和 artifact 脱敏，但 TLS、WAF、网关鉴权、集中密钥管理、网络隔离、容器运行时安全策略都依赖部署环境。生产部署不能只依赖应用自身配置。

### 4.10 数据生命周期和合规治理

历史记录、artifact、LLM usage、报告和知识库文档都有保留或清理机制的雏形，但还缺完整的数据分级、保留策略、删除审计、敏感数据分类和备份恢复制度。如果处理真实业务数据，这一块必须补齐。

### 4.11 系统复杂度上升

项目已经从单一生成器扩展为 RAG、Agent workflow、异步队列、测试执行、报告、监控、前端工作台和发布检查的组合系统。后续如果继续堆功能而不维护测试、文档和模块边界，复杂度会成为主要风险。

## 5. 风险优先级

| 优先级 | 风险 | 当前状态 | 建议 |
| --- | --- | --- | --- |
| P0 | 真实密钥或私有资料误发布 | 运行结果统一脱敏、ignore 和文档整合已降低风险，但生产密钥托管和发布前 secret scanning 仍需制度化 | 发布前继续做敏感信息扫描，保留 `.env.runtime`、缓存和 benchmark history 的 ignore，并把真实密钥交给部署侧密钥管理 |
| P1 | 公网部署权限不足 | API key 可用，但无用户/RBAC/项目隔离/审计 | 公网前必须加网关、TLS、用户、权限和审计设计 |
| P1 | 线上不可观测 | 有 readiness/queue check、内部 metrics、告警模板、示例配置和离线验证，无正式采集/告警 | 接入真实 Prometheus/Alertmanager，校准阈值并演练通知 |
| P1 | 真实模型质量随模型切换漂移 | 已有真实 LLM strict eval 和 benchmark 入口，样本仍需扩展 | 模型切换后必须跑真实 strict eval，并记录耗时、retry、timeout 和 429 趋势 |
| P1 | 生产数据库和队列容量未知 | MySQL/RQ service-mode 和 12 job 多轮负载 smoke 可用，但长时、高并发和组合故障验证不足 | 做更长时长、多 worker、受控并发和依赖抖动演练 |
| P1 | 队列一致性和失败恢复 | stale active job 恢复已补，RQ/DB 组合异常仍需实机验证 | 定期运行 Redis/MySQL outage、RQ worker stability 和 workflow RQ/MySQL smoke |
| P2 | RAG 质量随知识库变化漂移 | 有固定评估，无线上召回监控和 rerank/hybrid 对比 | 扩评估集，记录召回趋势，评估 metadata filter、rerank 和 hybrid search |
| P2 | 部署安全依赖外部环境 | 应用内配置校验已加强，TLS/WAF/密钥托管/网络隔离不在应用内 | 生产部署必须走网关、HTTPS、集中密钥管理和网络隔离 |
| P2 | 数据生命周期和合规治理不足 | 有 artifact 保留期和历史库清理基础，无完整数据分级/审计 | 定义保留、删除、备份、恢复和敏感数据分级策略 |
| P2 | 前端仍是内部工作台 | 已有 TestPlanPanel 和核心测试，不是企业管理后台 | 后续新功能保持组件边界和测试同步，再补权限视图和协作能力 |
| P3 | 系统复杂度上升 | release checks 和文档已兜底，但模块数量增长快 | 控制功能堆叠，优先治理安全、监控、权限和质量趋势 |

## 6. 推荐下一阶段

建议把后续工作分成三个层次，不再平均用力。

第一优先级：安全和生产运行治理

- 将内部 metrics JSON/Prometheus 输出接入真实监控系统，并按完整业务周期校准业务阶段失败率、耗时和队列阈值。
- 把 12 job service-mode smoke 扩展为更长时长、多 worker、受控并发和依赖抖动演练，并把结果写入运维证据。
- 为队列积压、RQ failed registry、生成失败率、service-mode worker 缺失和 readiness 失败定义正式告警路由。
- 保持运行结果脱敏回归和发布前 secret scanning，避免真实样本或密钥进入仓库、日志和 benchmark history。
- 把真实 LLM strict workflow eval 和 benchmark history 纳入模型切换检查，记录通过率、失败码、timeout、retry、429 和阶段耗时。

第二优先级：权限和数据边界

- 设计用户、项目、知识库和生成历史的隔离模型。
- 引入 key 轮换、最小权限和审计日志。
- 明确公网部署必须走网关、HTTPS 和集中密钥管理。

第三优先级：RAG 和业务落地

- 扩展更多业务模块固定评估集。
- 扩展更多真实业务 workflow 样本，并优先用真实 LLM strict eval 验证模型约束效果。
- 引入 metadata filter 和 rerank 对比评估。
- 继续扩展 pytest adapter，从登录扩展到退款等业务 API。

## 7. 当前不建议做的事

- 不建议立刻把 MySQL 切为默认 backend；应先完成更长时长稳定性和故障演练。
- 不建议继续大规模重构前端 layout；除非有明确交互问题，否则保持当前组件边界即可。
- 不建议直接做多租户 SaaS 化；应先补权限模型、审计和部署治理。
- 即使运行结果脱敏闭环已完成，也不建议直接用真实生产敏感响应做内部演示；应使用假数据、脱敏环境或受控样本。
- 不建议把真实 LLM smoke 放入默认 CI；它会消耗额度且受网络和模型状态影响。但重要发布、模型切换或 Prompt 契约调整后，不建议只看离线测评，必须手动跑真实 LLM strict workflow eval。

## 8. 评估结论

项目优化计划的本地交付目标基本完成。当前版本可以作为“内部可运行基线”使用，并且具备继续生产化的结构基础。

下一阶段不应再追求功能堆叠，而应转向运行治理：metrics、告警、权限边界、故障演练和 RAG 质量趋势。
