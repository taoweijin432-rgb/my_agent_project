# Agent 架构与面试技术点

这份文档用于解释本项目从“LLM 调用服务”升级到“可观测 Agent 工作流”的设计。它同时服务于后续开发、复盘和面试表达。

## 1. 当前 Agent 定位

本项目不是聊天型 Agent，而是面向测试用例生成的任务型 Agent。

输入是一段需求、PRD 或功能说明；输出是结构化测试用例。Agent 的职责不是自由对话，而是稳定完成一个工程任务：

```text
需求输入 -> 需求分析 -> 知识检索 -> 测试策略规划 -> Prompt 构造 -> LLM 生成 -> Schema 校验 -> 后处理 -> 质量评分/历史记录
```

当前核心实现：

- `app/services/generator.py`：生成入口和工作流执行。
- `app/services/agent_workflow.py`：轻量工作流状态、节点抽象、需求分析、测试策略规划。
- `app/services/rag.py`：长期知识库检索。
- `app/services/prompt.py`：Prompt 模板。
- `app/services/quality.py`：生成结果质量评分。
- `app/services/history.py`：生成历史和回放。
- `app/services/usage.py`：用量和估算成本统计。

## 2. 为什么先做轻量工作流，而不是直接上 LangGraph

直接引入 LangGraph/LangChain 不是错误，但当前阶段更适合先做轻量编排。

原因：

- 当前任务链路固定，不需要复杂分支图。
- 业务风险在可观测性、校验、历史记录和 RAG 质量，不在框架本身。
- 轻量节点更容易测试，也不会引入额外依赖和学习成本。
- 当节点边界稳定后，可以平滑迁移到 LangGraph。

本项目当前的工作流节点是：

```text
analyze_requirement
retrieve_knowledge
plan_test_strategy
build_prompt
call_llm
validate_output
post_process_cases
estimate_usage
```

这些节点会写入 `metadata.workflow_steps`，用于排查“是哪一步影响了生成结果”。

当前已经引入两个接近真实 Agent 框架的核心抽象：

- `GenerationWorkflowState`：一次生成请求里的短期记忆，保存 request、analysis、contexts、plan、attempt、prompt、payload、cases、usage 和 last_error。
- `WorkflowNode`：节点定义，包含节点名、节点动作和节点摘要。
- `WorkflowRecorder.run_node()`：统一执行节点，并把成功、失败、耗时和摘要写入 trace。

这相当于一个最小状态机。节点不再只依赖函数返回值串联，而是读写同一个 state。后续迁移 LangGraph 时，可以把 `WorkflowNode` 映射为 graph node，把 `GenerationWorkflowState` 映射为 graph state。

## 3. 工作流为什么这样设计

### 3.1 需求分析放在 RAG 前

需求分析是本地确定性逻辑，不调用大模型。它提取：

- 需求长度。
- 用户显式关注的用例类型。
- 安全、性能、兼容性等风险关键词。

这样做的好处：

- 成本为零。
- 可测试、可解释。
- 能提前影响后面的测试策略。

### 3.2 RAG 放在 Prompt 构造前

RAG 的作用是把企业知识放进上下文，减少模型编造。

当前检索结果会进入 Prompt，并且 metadata 会记录：

- `retrieved_chunks`
- `retrieved_sources`
- `source`
- `document_type`
- `module`
- `version`
- `content_hash`
- `updated_at`

面试中可以说：RAG 不是简单把文档塞给模型，而是把外部知识作为可追踪、可评估、可版本化的上下文。

### 3.3 测试策略规划放在 LLM 前

`plan_test_strategy` 是一个“Planner”节点。它会基于需求分析和知识来源决定目标覆盖类型，例如：

- functional
- boundary
- exception
- permission
- security
- performance
- compatibility

Planner 的结果会被注入 Prompt，告诉 LLM 本次生成应该重点覆盖什么。

这样比只写一个大 Prompt 更可控，因为策略是显式节点，可以单测，也可以在历史记录里追踪。

### 3.4 LLM 只负责最适合它的部分

当前设计里，LLM 主要负责生成自然语言测试用例。

不让 LLM 负责：

- 鉴权。
- 数据落库。
- 文件导出。
- 格式最终校验。
- 成本统计。
- 质量评分。

这些都由确定性代码完成。这样系统更稳定，也更容易通过测试证明行为。

## 4. 记忆架构

Agent 常见记忆可以分为三类：短期记忆、长期记忆、情景记忆。

### 4.1 短期记忆

短期记忆是一次请求中的工作状态。

本项目里包括：

- `GenerateRequest`
- RAG 检索到的 `KnowledgeChunk`
- Planner 输出的测试策略。
- Prompt messages。
- LLM 原始 payload。
- Pydantic 校验错误。
- workflow trace。

短期记忆由 `GenerationWorkflowState` 显式承载，只在一次生成流程中传递，不直接持久化。持久化的是最终请求、响应、失败原因、usage 和质量评分。

### 4.2 长期记忆

长期记忆是企业知识库。

本项目使用 Chroma 存储：

- PRD。
- API 文档。
- 测试规范。
- 历史业务规则。
- 从其他项目导出的 `knowledge_export/`。

长期记忆通过 embedding 检索进入 Prompt。

### 4.3 情景记忆

情景记忆是 Agent 过去做过什么。

本项目用 SQLite 保存生成历史：

- 请求。
- 响应。
- 失败原因。
- 耗时。
- 质量评分。
- usage 统计。
- request id。

情景记忆的价值是：

- 支持问题回放。
- 支持质量趋势。
- 支持成本统计。
- 支持后续做“参考历史生成”的 few-shot 增强。

## 5. 历史上下文很长时怎么压缩

面试里经常会问：上下文太长怎么办？

本项目当前和后续设计可以分为四层。

### 5.1 入口层压缩

不要直接把所有文档塞给模型。当前做法是：

- 文档按 chunk 切分。
- 查询时只取 top_k。
- 默认 `knowledge_top_k <= 10`。

### 5.2 检索层压缩

使用 embedding 检索，把长文档压缩成少量相关片段。

后续可以继续增强：

- metadata filter：按 project、module、document_type 过滤。
- rerank：先召回 top 20，再重排 top 5。
- query rewrite：把需求改写成更适合检索的问题。

### 5.3 记忆层压缩

历史生成记录不能无限塞进 Prompt。正确做法是提炼摘要：

- 保存完整历史到 SQLite。
- 回放时只取质量高、相似度高的历史记录。
- 对长历史生成“经验摘要”，例如常见边界、常见权限风险。

### 5.4 Prompt 层压缩

Prompt 中只保留对生成有用的信息：

- 当前需求。
- 相关知识片段。
- 测试策略。
- JSON Schema。
- 少量 few-shot。

不放：

- 全量日志。
- 全量历史。
- 不相关文档。
- 大段重复规范。

## 6. 如何降低幻觉

本项目用了多层防护：

- RAG：提供业务事实来源。
- Prompt：要求不要编造知识库没有支持的业务规则。
- Schema：强制输出 JSON object。
- Pydantic：后端校验字段和类型。
- Retry：校验失败时把错误反馈给模型重试。
- post-process：去重、截断、重排 ID。
- quality score：检查类型覆盖、重复、步骤完整度和知识 grounding。

面试表达可以是：不把“防幻觉”全部押在 Prompt 上，而是用检索、约束、校验、重试、评分组成防线。

## 7. Tool Calling 怎么接

当前项目还没有真正使用模型函数调用，但已经具备工具边界。

已有工具能力：

- `RagService.search`
- `RagService.upsert_document`
- `RagService.delete_document`
- `GenerationHistoryStore.list_records`
- `GenerationHistoryStore.get_record`
- `build_excel`
- `score_generation_quality`

后续如果做 Tool Calling，可以把这些能力封装成工具：

```text
search_knowledge(query, top_k)
list_generation_records(status, limit)
get_generation_record(record_id)
score_cases(cases)
export_cases(cases)
```

注意：不是所有功能都应该开放给 LLM。删除知识库、导出文件、写入历史这类操作需要权限和确认。

## 8. Agent 评估怎么做

Agent 不能只看“能不能生成”，要评估多个层面。

当前已有：

- 单元测试。
- API 测试。
- RAG eval cases。
- 生成质量评分。
- usage 统计。

后续建议增加：

- 固定需求回归集。
- 每次 prompt/version 改动后跑生成质量对比。
- 记录 pass rate、平均分、重复率、类型覆盖率。
- RAG source hit rate 和 keyword hit rate。

## 9. Agent 生产化常见问题

### 9.1 如何处理重试

当前只对格式校验失败进行生成重试，重试次数由 `LLM_MAX_RETRIES` 控制。

要注意：

- 重试会增加成本。
- 重试需要记录 attempts。
- 重试后的 prompt 应包含上一次错误。
- 不应该无限重试。

### 9.2 如何处理幂等

生成接口现在不是幂等接口，因为同一个输入可能生成不同输出。

后续可以增加：

- `request_id`
- 输入 hash。
- 缓存相同输入的生成结果。
- 用户确认后再落正式用例库。

### 9.3 如何做安全隔离

当前已经有：

- API key 鉴权。
- CORS 限制。
- 生产启动校验。
- 敏感文件忽略。

后续多人系统需要：

- 用户体系。
- project_id 隔离。
- 多知识库权限。
- 操作审计。

### 9.4 如何控制成本

当前已有：

- attempts。
- duration。
- usage 估算。
- estimated_cost。
- API key 限流。

后续可以增加：

- 每日额度。
- 每用户额度。
- 高成本请求审批。
- 真实 provider usage 采集。

### 9.5 如何选择模型

测试用例生成不是纯聊天任务，更看重：

- JSON 稳定性。
- 中文理解。
- 长上下文能力。
- 成本。
- 响应速度。

可以用小模型做初稿，大模型做评审；也可以用本地规则做预处理和评分，减少大模型调用。

## 10. 面试可讲的项目亮点

可以这样概括：

```text
我做了一个面向测试用例生成的 RAG Agent 服务。
它不是简单调 LLM，而是拆成需求分析、知识检索、测试策略规划、生成、结构化校验、质量评分、历史回放和成本统计的工作流。
系统用 Chroma 管理长期知识，用 SQLite 管理情景记忆，用 Pydantic 做结构化约束，用 workflow trace 做可观测性。
生产侧做了 API key、CORS、限流、启动配置校验、Docker Compose 和敏感数据隔离。
```

如果面试官问“为什么不用一个 Prompt 直接生成”，可以回答：

```text
一个 Prompt 难以测试和排查。节点化之后，每一步都能记录输入输出摘要、耗时、失败原因，也能单独演进。例如 RAG 召回差和 LLM 输出格式错是不同问题，应该在不同节点定位。
```

如果问“你的 Agent 记忆是什么”，可以回答：

```text
短期记忆是一次请求里的 workflow state；长期记忆是 Chroma 知识库；情景记忆是 SQLite 生成历史。三者分开后，既能控制上下文长度，也能支持回放、评估和持续优化。
```

如果问“长上下文怎么处理”，可以回答：

```text
我不会把全量历史塞进模型，而是用 chunk、embedding 检索、top_k、metadata filter、后续 rerank 和历史摘要来压缩。进入 Prompt 的只保留当前任务最相关的信息。
```

## 11. 后续可升级为真正框架的路线

第一阶段，当前已经完成：

- 显式工作流节点。
- `GenerationWorkflowState` 状态对象。
- `WorkflowNode` 节点抽象。
- workflow trace。
- RAG 长期记忆。
- SQLite 情景记忆。
- 质量评分。
- usage 统计。

第二阶段，可以引入 LangGraph：

- 把节点改成 graph node。
- 将 `GenerationWorkflowState` 映射为 graph state。
- 增加条件边：检索不足 -> query rewrite；质量低 -> reviewer repair；成本超限 -> 人工确认。

第三阶段，做多 Agent：

- Planner Agent：拆解测试策略。
- Generator Agent：生成用例。
- Reviewer Agent：审查覆盖和质量。
- Exporter Tool：导出和平台适配。

不要为了框架而框架。真正有价值的是：状态清晰、节点可测、失败可恢复、成本可控、结果可评估。
