# 知识库文档目录

把真实业务知识放到这个目录，再通过导入脚本写入 Chroma。

推荐目录：

```text
knowledge/
  prd/              PRD、需求说明、用户故事
  api/              接口文档、字段规则、错误码
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
