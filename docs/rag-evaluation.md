# RAG 评估说明

## 目标

RAG 评估用于验证“用户查询是否能召回正确知识片段”。它不是测试 LLM 生成质量，而是测试知识库检索质量。

评估集位置：

```text
tests/fixtures/rag_eval_cases.json
tests/fixtures/login_rag_eval_cases.json
```

每条用例包含：

- `id`：用例编号。
- `query`：模拟用户问题。
- `expected_sources`：期望 top-k 结果中命中的文档。
- `expected_keywords`：期望召回内容中出现的关键词。

## 运行方式

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --top-k 5
```

输出 JSON：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --top-k 5 --json
```

作为门禁运行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py `
  --top-k 5 `
  --fail-under-source-hit-rate 0.8 `
  --fail-under-keyword-hit-rate 0.8
```

登录模块固定评估集：

```bash
EMBEDDING_PROVIDER=hash \
CHROMA_PATH=data/chroma-login-rag-eval \
CHROMA_COLLECTION=login_rag_eval_hash \
./.venv/bin/python scripts/evaluate_rag.py \
  --cases tests/fixtures/login_rag_eval_cases.json \
  --top-k 5 \
  --case-keyword-ratio 1.0 \
  --fail-under-source-hit-rate 1.0 \
  --fail-under-keyword-hit-rate 1.0
```

## 当前基线

最近一次评估：

```text
cases: 12
source_hits: 12
source_hit_rate: 1.0
keyword_hits: 36
keyword_total: 38
keyword_hit_rate: 0.9474
case_passes: 12
case_pass_rate: 1.0
```

当前检索配置：

```text
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
CHROMA_COLLECTION=test_knowledge_bge_small_zh_v15
top_k=5
```

登录模块固定评估基线：

```text
cases: 7
source_hits: 7
source_hit_rate: 1.0
keyword_hits: 36
keyword_total: 36
keyword_hit_rate: 1.0
case_passes: 7
case_pass_rate: 1.0
```

登录评估使用隔离 collection：

```text
EMBEDDING_PROVIDER=hash
CHROMA_PATH=data/chroma-login-rag-eval
CHROMA_COLLECTION=login_rag_eval_hash
top_k=5
```

## 维护规则

- 每次新增真实业务文档后，补充至少 1 条对应 RAG 评估用例。
- 每次调整 chunk size、embedding 模型、collection 或导入策略后，重新运行评估。
- 运行登录评估时不要导入 `knowledge/evaluation/` 到被评估 collection，避免评估集文本本身被召回造成虚高。
- 如果 source hit rate 下降，优先检查文档是否未导入、metadata 是否错误、query 是否过泛。
- 如果 keyword hit rate 下降，优先检查 chunk 是否过短、关键词是否只出现在相邻 chunk、文档是否被截断。

## 当前观察

- 认证、权限、问卷、模型中心、预警、AI 用例生成和安全基线均能命中对应文档。
- 个别查询会召回相关但不完全精确的文档，例如系统总览查询会同时命中验收模板。这不是阻断问题，但后续可以通过 rerank、metadata filter 或更细的 query rewrite 改善。
