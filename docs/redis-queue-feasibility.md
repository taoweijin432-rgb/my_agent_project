# Redis/RQ 外部队列评估与实现记录

最后更新：2026-06-22

## 1. 当前结论

Redis/RQ 外部队列已经完成第一阶段实现和 smoke 验证。后续数据库 backend 抽象也已完成，MySQL backend 已通过本机 Docker MySQL smoke；默认 backend 仍是 SQLite。

已实现内容：

- 保留原有异步任务 API 路径和响应模型。
- 保留 `in_memory` backend，作为本地开发和单元测试 fallback。
- 新增 `rq` backend，API 只负责创建任务状态并把 `job_id` 投递到 Redis/RQ。
- 新增 `generation_jobs` 任务状态表，任务请求、状态、响应、错误和 `record_id` 以数据库 backend 为准。
- 新增独立 worker 入口 `scripts/run_generation_worker.py`，worker 复用生成链路、历史落库、门控和异常映射。
- Docker Compose 增加 Redis、worker、Redis volume 和健康检查。
- 轻量 smoke 构建拆出 `requirements-smoke.txt` 和 `docker-compose.smoke.yml`，用于验证 Redis/RQ 闭环，避免下载完整 Chroma/ML 依赖。

已验证结果：

```bash
./.venv/bin/python -m pytest tests/test_generator.py tests/test_generation_jobs.py tests/test_generation_job_store.py tests/test_deployment_templates.py -q
# 24 passed

docker build --check .
# Check complete, no warnings found.

REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml build
REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
```

Compose smoke 中提交异步任务 `0031c4a8a92d4912893bfe2ed8a7556a` 后，worker 成功消费，最终状态为 `failed`，`error.code=budget_exceeded`，SQLite 写入 `generation_jobs` 和 `generation_records`，RQ 队列长度为 `0`。后续 Redis/RQ + MySQL smoke 也已通过：任务最终 `status=failed`、`error.code=budget_exceeded`，MySQL 写入任务状态和生成历史，RQ 队列长度为 `0`。

阶段评估：正常。Redis/RQ 升级目标已经达成；MySQL backend 已完成第一阶段接入，下一阶段应优先补 MySQL 生产化和 Docker 生产硬化。

## 2. 原始评估结论

把当前进程内 `InMemoryGenerationJobQueue` 升级为 Redis 外部队列是可行的，建议第一阶段采用 Redis + RQ，而不是直接引入 Celery。

推荐路径：

1. 保留现有 API 路径和响应模型。
2. 新增任务队列接口，继续保留进程内实现作为本地开发和单元测试 backend。
3. 新增持久化任务状态表，第一阶段先落 SQLite，后续已通过数据库 backend 抽象接入 MySQL。
4. 新增 Redis/RQ adapter，只把 `job_id` 投递到 Redis，任务请求、状态、响应和错误以数据库为准。
5. 新增独立 worker 启动入口，worker 复用现有生成链路、历史落库、门控和异常映射。
6. 更新 Docker Compose，增加 `redis` 和 `worker` 服务。

阶段评估：该判断已被实现验证。方案能解决多进程 API 不共享内存队列的问题，同时不强行把 Redis 当作长期结果数据库。

## 3. 原始进程内基线

当前异步队列集中在 `app/services/generation_jobs.py`：

- `submit()` 创建内存任务记录并写入 `queue.Queue`。
- 后台 daemon thread 从队列取 `job_id`，调用原生成链路。
- `get_job()` 和 `list_jobs()` 直接读取进程内 `_jobs` 字典。
- 队列满时抛出 `GenerationJobQueueFullError`，API 映射为 429。
- 完成任务会在内存记录中保存 `response`、`record_id` 或 `error`。

API 层当前只依赖三个队列方法：

- `POST /api/v1/test-cases/generation-jobs` -> `submit()`
- `GET /api/v1/test-cases/generation-jobs` -> `list_jobs()`
- `GET /api/v1/test-cases/generation-jobs/{job_id}` -> `get_job()`

现有响应模型已经稳定：

- `GenerationJobSummary`
- `GenerationJobDetail`
- `GenerationJobError`
- `GenerationJobListResponse`

关键限制：

- 任务状态只在进程内，API 多进程或多实例后互不可见。
- 进程重启后已排队和已完成任务都会丢失。
- worker 是 API 进程内线程，扩缩容和部署边界不清晰。
- SQLite 历史表只记录生成结果和门控，不记录异步任务自身状态。

阶段评估：该判断成立。当前 API 对队列实现的耦合较浅，迁移难点主要在任务状态持久化和 worker 进程拆分，而不是路由层。

## 4. 方案对比

### Redis + RQ

适配度：高。

优点：

- 模型简单，适合当前单一长任务队列。
- worker 启动方式直观，运维成本低。
- 依赖少，迁移范围小。
- 与现有 `queued/running/succeeded/failed` 状态可以直接映射。

限制：

- 队列长度上限和严格背压需要额外实现，RQ 本身不等同于有界队列。
- 复杂工作流、任务编排、定时任务和高级路由能力弱于 Celery。
- 不能只依赖 RQ result ttl 保存 API 查询结果，否则任务详情仍会随 Redis 过期策略丢失。

### Redis + Celery

适配度：中。

优点：

- 生态成熟，重试、路由、调度、监控和多 broker 支持更完整。
- 后续如果生成链路拆成多个异步步骤，Celery canvas 更方便。

限制：

- 对当前项目偏重，引入配置、worker 生命周期和测试复杂度更高。
- 默认状态后端也不是业务审计数据库，仍然需要任务状态表。
- 第一阶段只替换一个生成队列时，收益不足以抵消复杂度。

### 直接使用 Redis List/Stream

适配度：中低。

优点：

- 可完全控制队列长度、消费确认、消息结构和重试策略。

限制：

- 需要自行实现 worker、ack、失败队列、重试、超时和可观测性。
- 当前目标是生产化升级，不建议在已有成熟库可用时手写队列基础设施。

阶段评估：正常，可以继续。第一阶段选择 RQ 更稳，Celery 保留为后续复杂编排升级选项。

## 5. 当前目标架构

```text
Client
  |
FastAPI API
  |
GenerationJobQueue interface
  |---- InMemoryGenerationJobQueue   local/test fallback
  |
  |---- RedisRQGenerationJobQueue
          |
          | enqueue(job_id)
          v
        Redis / RQ
          |
        Worker process
          |
        Generation job runner
          |
        TestCaseGenerator + RAG + LLM + Reviewer + Gates
          |
        GenerationHistoryStore + GenerationJobStore
```

推荐新增模块：

- `app/services/generation_job_store.py`：持久化任务状态、请求、响应、错误、时间戳和 `record_id`。
- `app/services/generation_job_queue.py` 或继续扩展 `generation_jobs.py`：定义队列接口和 backend factory。
- `app/services/generation_execution.py`：把 `_execute_generation()` 从 API routes 中移出，供同步 API、RQ worker 和内存队列复用。
- `app/workers/generation_rq.py`：RQ worker 可导入的任务函数，例如 `run_generation_job(job_id: str)`。
- `scripts/run_generation_worker.py`：本地启动 worker 的薄封装。

任务状态以数据库为准，Redis 只负责派发：

```text
submit:
  create generation_jobs row(status=queued, request_json=...)
  enqueue RQ job with job_id
  return row as GenerationJobDetail

worker:
  load job row
  mark running
  run generation
  mark succeeded or failed

query/list:
  read generation_jobs table
```

阶段评估：正常，可以继续。数据库作为状态源能保持 API 查询语义稳定，也为后续 MySQL 升级留出自然边界。

## 6. 数据模型

已新增 `generation_jobs` 表：

| 字段 | 说明 |
| --- | --- |
| `id` | 与 API 返回的 `job_id` 一致 |
| `queue_backend` | `in_memory` / `rq` |
| `queue_job_id` | RQ 内部 job id，可与 `id` 相同 |
| `status` | `queued` / `running` / `succeeded` / `failed` |
| `created_at` | 提交时间 |
| `updated_at` | 最近更新时间 |
| `started_at` | worker 开始时间 |
| `finished_at` | 完成时间 |
| `request_json` | `GenerateRequest` |
| `response_json` | 成功时的 `GenerateResponse` |
| `error_json` | 失败时的 `GenerationJobError` |
| `record_id` | 对应生成历史记录 |
| `worker_id` | 可选，记录执行 worker |
| `attempts` | 可选，当前执行次数 |

保留 `GENERATION_JOB_RETENTION_SECONDS` 语义：清理已完成任务状态。生成历史仍由 `generation_records` 保留，任务状态清理不影响历史审计。

阶段评估：正常，可以继续。模型能完整覆盖现有 API 输出，不需要改前端或调用方契约。

## 7. 背压与并发

当前进程内队列用 `queue.Queue(maxsize=...)` 提供强背压。迁移到 RQ 后需要重新定义。

当前第一阶段实现：

- `GENERATION_JOB_MAX_WORKERS` 仍控制进程内 backend 的线程数；RQ backend 下真实并发由 worker 进程或容器数量决定。
- `GENERATION_JOB_MAX_QUEUE_SIZE` 继续保留，用数据库中 `queued/running` 数量做提交前检查。
- 队列已满时仍返回 429，保持现有 API 行为。
- 这是近似背压；如果需要多 API 实例严格并发提交保护，再用 MySQL 事务、Redis Lua 脚本或单独计数器做原子检查。

需要注意：

- RQ 没有内建等价于 `queue.Queue(maxsize)` 的强有界队列。
- 多个 API 实例同时提交时，简单 `LLEN` 检查会有竞态。
- 对当前单 API 实例或低并发受控部署，近似背压可以接受。

阶段评估：正常，但有实现风险。第一阶段可以先接受近似背压并写入文档；如果目标是多 API 实例高并发接单，应把原子背压列为必须项。

## 8. 失败恢复

必须处理的失败场景：

- Redis 不可用：提交异步任务返回 503 或按配置降级到 in-memory。
- enqueue 成功但 API 响应失败：任务已存在，客户端可用返回的 job id 时查询；若响应前失败且客户端未知，需要依赖调用方重试。
- 数据库写入成功但 enqueue 失败：任务应标记 failed 或回滚删除，并返回明确错误。
- worker 执行异常：复用现有 `_error_from_exception()` 映射为 `GenerationJobError`。
- worker 进程崩溃：任务可能停留在 `running`，需要 stale job reconciliation。
- Redis 重启：已排队任务取决于 Redis 持久化配置；业务状态表仍可用于识别未完成任务。

当前已实现：

- worker 启动时扫描超时 `running` 任务，并标记为 failed。
- Redis 不可用或 enqueue 失败时，提交接口返回 503，业务任务状态写入 failed。
- worker 执行异常会复用 `_error_from_exception()` 映射为结构化 `GenerationJobError`。

仍需补强：

- API 健康检查或管理接口暴露 Redis 连接状态。
- RQ failed registry 与业务表做对账。
- 多实例下的原子背压和 MySQL 事务边界。

阶段评估：正常，但不能忽略 crash recovery。若不做 stale running 处理，外部队列升级后仍会有任务永远卡住的生产问题。

## 9. 与数据库 backend 的关系

默认可以继续使用 SQLite：

- 当前 worker 数默认较低。
- 生成历史已经用锁和短连接写入。
- 本地或单机 Docker Compose 场景可接受。

MySQL backend 当前状态：

- 已新增 `DATABASE_BACKEND=sqlite|mysql` 和 `DATABASE_URL`。
- 已新增 `requirements-mysql.txt`、`migrations/mysql/001_initial.sql` 和 `scripts/init_mysql.py`。
- 已用本机 Docker MySQL 完成 store smoke 和 Redis/RQ worker smoke。
- 默认仍是 SQLite，避免把生产切换和功能迁移绑在同一阶段。

仍需要明确边界：

- 多 worker 进程同时写 SQLite 时可能遇到 database locked，需要设置超时、控制 worker 数，或切换到 MySQL backend。
- 多主机部署不能共享本地 SQLite 文件。
- 真正多实例生产应使用 MySQL backend，并补齐备份恢复、连接池参数、原子背压和稳定性验证。

阶段评估：正常。SQLite 仍适合作为默认开发 backend；MySQL backend 已能支撑任务状态、生成历史和门控写回闭环，但生产默认切换还需要硬化。

## 10. 配置与部署

已新增配置：

```env
GENERATION_JOB_QUEUE_BACKEND=rq
REDIS_URL=redis://redis:6379/0
RQ_QUEUE_NAME=generation
RQ_JOB_TIMEOUT_SECONDS=900
RQ_RESULT_TTL_SECONDS=3600
RQ_FAILURE_TTL_SECONDS=86400
GENERATION_JOB_STALE_AFTER_SECONDS=1800
```

`docker-compose.yml` 已新增：

- `redis` 服务。
- `worker` 服务，与 API 使用同一镜像和 `.env.runtime`。
- API 通过 `depends_on` 等待 Redis 启动。
- Redis 增加 volume 和健康检查。

`requirements.txt` 已新增：

```text
redis>=5.0.0
rq>=1.16.0
```

阶段评估：正常，可以继续。部署改动清晰，依赖体量明显小于 Celery。

## 11. 运行方式速查

本机 Python API/worker + Docker Redis：

```bash
export REDIS_URL=redis://127.0.0.1:6379/0
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
./.venv/bin/python scripts/run_generation_worker.py
```

Docker Compose 完整服务：

```bash
docker compose up -d --build
docker compose ps
```

Redis/RQ 轻量 smoke：

```bash
REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml build
REDIS_HOST_PORT=6380 docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
```

smoke 预期：提交 `knowledge_top_k=0` 且 `AGENT_BUDGET_MAX_PROMPT_TOKENS=1` 的异步生成任务后，最终 `status=failed`、`error.code=budget_exceeded`。这表示 API 入队、Redis/RQ、worker 消费、预算门控、任务状态持久化和历史落库都已跑通。

Linux 权限注意：正式 `docker-compose.yml` 使用 `./data:/app/data` bind mount。若宿主目录由 `root` 创建且权限为 755，容器内非 root 用户 `appuser` 会无法写 SQLite。轻量 smoke compose 使用 named volume 避免这个问题；正式部署需确保宿主数据目录对容器用户可写。使用 MySQL backend 时，应用容器不再依赖 SQLite 文件写入任务状态和历史，但仍要持久化 Chroma、日志或其他运行数据目录。

阶段评估：正常。当前运行方式已经覆盖本机开发、Compose smoke 和正式 Compose 模板。

## 12. 测试计划

已保留测试：

- `tests/test_generation_jobs.py` 继续覆盖进程内队列。
- `tests/test_generate_api.py` 继续用 fake queue 覆盖 API 契约。

已新增或已覆盖测试：

- `GenerationJobStore` 的创建、状态流转、列表过滤、过期清理。
- Redis/RQ adapter 的提交成功、队列满、Redis 不可用错误映射。
- worker 任务入口和 stale running 任务失败标记。
- stale running 任务恢复或失败标记。
- 配置读取和生产启动校验。
- Docker Compose 模板包含 `redis` 和 `worker`。

可选集成测试：

- 使用本机 Redis 跑 RQ worker smoke test。
- 如果不要求本机 Redis，则把 Redis 集成测试标记为可跳过。

阶段评估：正常。当前测试结构已经承接该迁移；MySQL 阶段已补数据库兼容测试和迁移测试，后续重点转向生产稳定性验证。

## 13. 实施分阶段记录

### Phase 1：抽象和状态持久化

- 定义队列接口。
- 新增 `GenerationJobStore`。
- 将生成执行逻辑从 API routes 移到 service。
- InMemory 队列改为通过 store 更新状态，行为保持不变。
- 测试通过。

阶段状态：已完成。API 响应不变，旧 in-memory backend 测试通过。

### Phase 2：接入 Redis/RQ

- 新增依赖和配置。
- 新增 RQ adapter。
- 新增 worker 入口。
- Redis 不可用时返回明确错误。
- 队列满继续返回 429。
- 增加 worker 测试和本机 smoke test。

阶段状态：已完成。异步提交、查询、门控失败链路已在 RQ backend 下通过；成功链路仍依赖真实 LLM，应在受控环境单独验证。

### Phase 3：部署与文档

- Docker Compose 增加 Redis 和 worker。
- 更新 `.env.runtime.example`、部署文档、README 和 issues。
- 增加 Redis/RQ 运维注意事项。

阶段状态：已完成。相关测试、Dockerfile 静态检查和轻量 Compose smoke 通过。

### Phase 4：生产增强

- 加强原子背压。
- 增加 stale job reconciliation。
- 增加队列长度、失败率、运行时长和 Redis 连接状态指标。
- 补齐 MySQL 生产化。

阶段状态：部分完成。MySQL backend 迁移已完成第一阶段实现和 smoke；Compose MySQL 模板、初始化、备份、恢复文档、恢复演练、完整 Compose smoke 和 5 任务稳定性 smoke 已完成；多 worker 长任务压测、指标、失败对账和故障恢复验证仍是下一批生产增强。

## 14. 最终判断

可行性：高。

建议优先级：高，符合封版后第一批升级路线。

已落地方案：Redis + RQ + 数据库 backend 持久化任务状态表；默认 SQLite，可选 MySQL。

不建议第一阶段直接做：

- 直接上 Celery。
- 只用 RQ job result 保存任务详情。
- 手写 Redis List/Stream worker。
- 在没有任务状态表的情况下替换掉内存队列。

主要风险：

- RQ 背压不是强有界队列，需要额外约束。
- worker 崩溃会导致业务表中的 running 任务卡住，需要恢复策略。
- SQLite 不适合多 worker 高并发写入；MySQL backend 已可用，但生产默认切换还需要硬化。

总评估：正常。Redis/RQ 外部队列第一阶段已经可用；MySQL backend 已完成第一阶段接入。下一阶段应处理 MySQL 生产化、原子背压、队列可观测性和完整 ML/RAG 镜像验证。
