# 知识库文档目录

把真实业务知识放到这个目录，再通过导入脚本写入 Chroma。

推荐目录：

```text
knowledge/
  prd/              PRD、需求说明、用户故事
  api/              接口文档、字段规则、错误码
  security/         安全基线、攻击面、敏感数据规则
  audit/            审计事件、审计字段、日志脱敏规则
  evaluation/       RAG 查询评估集、期望命中 source 和关键词
  history-cases/    历史测试用例
  guidelines/       测试设计规范、通用检查清单
  defects/          缺陷复盘、线上问题记录
```

导入命令：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py knowledge --recursive
```

如果已经从其他项目提取了 `knowledge_export/`，可以一起导入：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_documents.py knowledge knowledge_export --recursive --reset
```

支持文件类型：`.md`、`.txt`。

Linux / WSL 环境可以使用：

```bash
./.venv/bin/python scripts/ingest_documents.py knowledge --recursive
```

目录下的一级子目录会自动作为 `document_type`，二级子目录会自动作为 `module`。例如：

```text
knowledge/prd/login/phone-login.md
```

会得到：

```text
document_type=prd
module=login
source=knowledge/prd/login/phone-login.md
```

不要把真实敏感业务文档提交到公开仓库。如果要开源项目，保留这个 README 和示例即可。

## 登录模块示例知识库

当前仓库内置一组登录模块示例知识库，用于演示 RAG 全链路测试用例生成：

```text
knowledge/prd/login/default-langgraph-full-chain.md      登录知识库索引
knowledge/prd/login/login-prd.md                         登录 PRD 和业务规则
knowledge/prd/login/login-acceptance-matrix.md           原子验收矩阵
knowledge/api/login/login-api-contract.md                登录接口字段、响应和错误码
knowledge/security/login/login-security-baseline.md      登录安全基线
knowledge/audit/login/login-audit-log.md                 登录审计日志要求
knowledge/evaluation/login-rag-eval-cases.md             RAG 评估查询集
```

生成登录测试用例时，优先导入全部上述文件。若只导入总览索引，RAG 可能召回不足；若只导入 PRD，模型容易漏掉安全、审计和接口字段断言。

## 订单退款模块示例知识库

订单退款模块用于验证非登录场景的 RAG 泛化能力：

```text
knowledge/prd/refund/refund-prd.md                  退款 PRD、状态、金额、审核和时效规则
knowledge/api/refund/refund-api-contract.md         退款创建、查询、审核 API 和幂等错误码
knowledge/risk/refund/refund-risk-rules.md          大额退款、频繁退款、黑名单等风控规则
knowledge/audit/refund/refund-audit-log.md          退款审计事件、字段和脱敏要求
tests/fixtures/refund_rag_eval_cases.json           订单退款 RAG 固定评估集
```

订单退款固定评估使用隔离 `refund_rag_eval_hash` collection，避免与登录或通用知识库互相影响。

`knowledge_export/` 使用同样的一级目录作为 `document_type`，文件名会作为 `module`。例如：

```text
knowledge_export/api/auth_permissions.md
```

会得到：

```text
document_type=api
module=auth_permissions
source=knowledge_export/api/auth_permissions.md
```
