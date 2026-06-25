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
