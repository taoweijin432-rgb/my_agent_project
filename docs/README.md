# 文档总览

这个目录保存项目的正式技术文档。为避免重复维护，文档按职责拆分：README 只做快速入口，详细说明放在专题文档中。

## 权威文档

| 内容 | 权威位置 |
| --- | --- |
| 项目定位、接口、配置、工作流、常见问题 | [project-guide.md](project-guide.md) |
| 架构分层和模块边界 | [architecture-baseline.md](architecture-baseline.md) |
| Agent workflow、状态、节点、门控和 LangGraph backend | [agent-architecture.md](agent-architecture.md) |
| Linux 本机 API/worker/Redis/MySQL 运行步骤 | [local-run.md](local-run.md) |
| 容器、生产配置、镜像、Compose 和上线检查 | [deployment.md](deployment.md) |
| 发布范围、验收标准、限制和后续工作 | [release-checklist.md](release-checklist.md) |
| 后续工程化、生产化和 RAG 治理计划 | [optimization-plan.md](optimization-plan.md) |
| 当前项目评估、主要缺口和下一阶段建议 | [project-assessment.md](project-assessment.md) |
| 测试执行 Agent 改造计划 | [test-agent-transformation-plan.md](test-agent-transformation-plan.md) |
| 测试执行 Agent 改造阶段评估 | [test-agent-transformation-assessment.md](test-agent-transformation-assessment.md) |
| RAG 固定评估、指标和运行命令 | [rag-evaluation.md](rag-evaluation.md) |
| 内部 metrics、Prometheus/Alertmanager 抓取和告警规则模板 | [monitoring.md](monitoring.md) |
| MySQL 初始化、备份、恢复和演练 | [mysql-operations.md](mysql-operations.md) |
| 登录场景效率评估结果 | [login-efficiency-report.md](login-efficiency-report.md) |

## 外部入口

- [../README.md](../README.md)：项目入口、最小启动路径和文档导航。
- [../frontend/README.md](../frontend/README.md)：React + Vite 前端工作台。
- [../knowledge/README.md](../knowledge/README.md)：可导入知识库目录结构。

## 依赖清单

后端依赖统一维护在 `requirements.txt`，关键版本上界维护在 `constraints.txt`。不要再新增按场景拆分的 `requirements-*.txt`；如果某个能力依赖体积较大或只在少数环境使用，把安装说明写到对应文档中。

## 维护规则

- README 不复制完整 API、配置表或部署细节，只保留入口和最小命令。
- 新接口和字段优先更新 `project-guide.md`，不要同时在多个文档写完整请求示例。
- 运行环境差异写入 `local-run.md` 或 `deployment.md`，不要放进架构文档。
- 发布范围、已知限制和后续工作只在 `release-checklist.md` 长期维护。
- `knowledge_export/` 和 `private_docs/` 是本地或私有资料，不作为公开权威文档来源。
