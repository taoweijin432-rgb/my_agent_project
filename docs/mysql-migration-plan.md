# MySQL 迁移评估

最后更新：2026-06-24

## 1. 结论

将当前 SQLite 运行数据库迁移到 MySQL 是可行的，并且更符合当前本机环境：MySQL 已通过 Docker 启动，项目可以在保留 SQLite fallback 的前提下接入 `DATABASE_BACKEND=mysql`。

推荐迁移范围：

- `generation_records`：生成历史、失败原因、usage、门控详情和门控审批结果。
- `generation_jobs`：异步任务请求、状态、响应、错误、worker、attempts 和 `record_id`。

初始化、备份和恢复操作见 [mysql-operations.md](mysql-operations.md)。

不迁移：

- Chroma 向量库数据，仍按 `CHROMA_PATH` 持久化。
- Redis/RQ 队列数据，Redis 仍只负责任务派发和短期 result registry。
- 模型缓存和知识库原始文件。

阶段评估：正常。MySQL 足够承载当前任务状态、历史记录和门控审批场景；JSON 字段用于保留 API payload，后续统计报表再考虑拆列。

## 2. 当前进展

已完成：

- 新增 `DATABASE_BACKEND=sqlite|mysql`。
- 新增 `DATABASE_URL` 配置和生产校验。
- 新增 `GenerationHistoryRepository` 和 `GenerationJobRepository` protocol。
- API、Redis/RQ queue、RQ worker 和生成执行器已改为依赖 repository protocol 或 factory。
- 新增 `requirements-mysql.txt`。
- 新增 `migrations/mysql/001_initial.sql`。
- 新增 `scripts/init_mysql.py`。
- 新增 `MySQLGenerationHistoryStore` 和 `MySQLGenerationJobStore` 代码路径。
- Dockerfile 已复制 `requirements-mysql.txt` 和 `migrations/`。

当前默认仍是 `DATABASE_BACKEND=sqlite`。本机 `.venv` 已安装 `requirements-mysql.txt`，Docker MySQL 已初始化 schema，并已完成 MySQL store、Redis/RQ smoke、备份恢复、完整 Compose smoke 和多任务稳定性 smoke。

## 3. MySQL 运行方式

本机 Docker MySQL 推荐命令：

```bash
docker run -d \
  --name my-mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=your_root_password \
  -e MYSQL_DATABASE=agent \
  -e MYSQL_USER=agent_user \
  -e MYSQL_PASSWORD=your_agent_password \
  -v mysql_data:/var/lib/mysql \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci
```

本机 Python 连接 Docker MySQL：

```text
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4
```

Docker Compose 容器内连接 MySQL 时 host 应使用服务名：

```text
DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
```

初始化 schema：

```bash
uv pip install --python ./.venv/bin/python -r requirements-mysql.txt
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/init_mysql.py
```

## 4. Schema 设计

第一阶段保持 API 契约和 store 方法不变：

- 主键：`varchar(64)`。
- 时间字段：`datetime(6)`，应用按 UTC 写入。
- JSON 字段：MySQL `json`。
- 状态字段：`varchar(16)` 加 check 约束。
- 字符集：`utf8mb4`、`utf8mb4_unicode_ci`。
- 引擎：`InnoDB`。

关键索引：

- `generation_records(created_at desc)`
- `generation_records(status)`
- `generation_records(gate_status)`
- `generation_jobs(created_at desc)`
- `generation_jobs(created_epoch desc)`
- `generation_jobs(status)`
- `generation_jobs(status, created_at)`

阶段评估：正常。当前查询主要按 `id`、`status`、`created_at` 和 `gate_status` 过滤，MySQL 索引能覆盖。

## 5. 验证结果

已完成：

- 已安装 `requirements-mysql.txt` 到 `.venv`。
- 已通过 `docker exec` 将 `migrations/mysql/001_initial.sql` 初始化到 `my-mysql` 容器的 `agent` 数据库。
- 已用 `DATABASE_BACKEND=mysql` 跑 history/job store 直接读写 smoke。
- 已用 Redis/RQ + MySQL 跑真实 API/worker smoke。
- 已用本机 Python API/worker + Docker Redis + Compose MySQL 跑端到端 smoke，并验证 MySQL 重启后记录仍可查询。
- 已用完整 Compose API/worker + Redis + MySQL 环境连续提交 5 条异步任务，并验证 MySQL 记录、RQ registry 和 API/worker 重启后读取。

当前已通过：

```bash
./.venv/bin/python -m pytest tests/test_config.py tests/test_stores.py tests/test_mysql_migration.py tests/test_deployment_templates.py -q
# 29 passed

# MySQL store smoke
# record_id=8739bf45e2754022bc8f5dad0afbde59
# job_id=53c78338800b4d1abb4c6cf63736f56f

# Redis/RQ + MySQL smoke
# job_id=7898d467d1c8498689dae88500f7d9b7
# status=failed, error.code=budget_exceeded
# record_id=01ba8a5b96fa434da56b4ef6b6468d42
# RQ queue length=0

# Redis/RQ + MySQL + API + worker smoke
# mode=local Python API/worker + Docker Redis + Compose MySQL
# mysql_project=agent_mysql_smoke
# mysql_host_port=3307
# queue=generation-mysql-smoke
# job_id=df50848d423d45c69fcc817454955c72
# status=failed, error.code=budget_exceeded
# record_id=8374573ace9c45afb80f88f6d9fd3bf1
# RQ queue length=0, finished_count=1
# MySQL restart persistence check=passed

# Full Compose API/worker + Redis + MySQL smoke
# project=agent_compose_mysql_smoke
# image=ai-testcase-generator:local
# build_requirements=requirements-mysql.txt
# api_host_port=8021, redis_host_port=6381, mysql_host_port=3309
# queue=generation-compose-smoke
# job_id=f34c9701f1734143bc5c034e86a20f69
# status=failed, error.code=budget_exceeded
# record_id=a31853c1f8b94e1d8019123371db283e
# RQ queue length=0, finished_count=1
# API/worker restart persistence check=passed

# Redis/RQ + MySQL + API + worker stability smoke
# project=agent_stability_mysql
# image=ai-testcase-generator:local
# build_requirements=requirements-mysql.txt
# api_host_port=8022, redis_host_port=6382, mysql_host_port=3310
# queue=generation-compose-smoke
# submitted_jobs=5
# final_status=failed for all jobs
# error.code=budget_exceeded for all jobs
# latest_job_id=f6d85795ef4e4174895e810ca942f0e0
# latest_record_id=0145d159593e4d97b81e05b5526b990b
# MySQL generation_jobs=5, generation_records=5
# MySQL status counts: failed=5 for both tables
# RQ queue_count=0, failed_count=0, finished_count=5
# API/worker restart persistence check=passed
```

## 6. 风险

- MySQL Docker volume 初始化后，`MYSQL_ROOT_PASSWORD`、`MYSQL_USER` 等环境变量不会再次重置旧数据。
- 本机 Python 使用 `127.0.0.1:3306`，容器内部使用 `mysql:3306`，不要混用。
- JSON 字段适合保存 payload；复杂分析统计后续应拆列。
- 默认 backend 仍是 `sqlite`；Compose MySQL 服务模板、初始化、备份、恢复说明、一次恢复演练、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke 已完成。切换生产默认值前仍建议补 worker crash、Redis/MySQL 短暂不可用和更长时长运行验证。

总评估：正常。MySQL backend 已能完成生成历史、任务状态、门控失败和 Redis/RQ worker 写回闭环，备份恢复链路、完整 Compose API/worker 镜像 smoke 和多任务稳定性 smoke 均已通过。下一阶段应进入 Docker 完整镜像、数据目录权限和队列可观测性硬化。
