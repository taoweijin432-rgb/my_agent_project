# MySQL 初始化、备份与恢复

最后更新：2026-06-23

本文记录项目使用 MySQL backend 时的本机和 Compose 运维步骤。MySQL 当前用于保存生成历史、门控审批和异步任务状态；Chroma 向量库、Redis/RQ 队列数据、模型缓存和原始知识库文件不在 MySQL 备份范围内。

## 1. 使用范围

MySQL 保存：

- `generation_records`：生成历史、失败原因、usage、质量报告、门控详情和审批状态。
- `generation_jobs`：异步任务请求、状态、响应、错误、worker、attempts 和 `record_id`。

MySQL 不保存：

- Chroma 向量库数据。
- Redis/RQ 队列 registry。
- `.model_cache/` 模型缓存。
- `knowledge/` 或 `knowledge_export/` 原始知识库文件。

阶段评估：正常。备份 MySQL 只能保护运行数据库，不能替代 Chroma 和知识库文件备份。

## 2. Compose 初始化

复制运行配置：

```bash
cp .env.runtime.example .env.runtime
```

编辑 `.env.runtime`，至少设置：

```env
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
MYSQL_ROOT_PASSWORD=replace-with-strong-root-password
MYSQL_DATABASE=agent
MYSQL_USER=agent_user
MYSQL_PASSWORD=your_agent_password
```

启动 Redis、MySQL、API 和 worker：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d --build
```

确认容器状态：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml ps
```

确认 MySQL schema：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
  sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "show tables;"'
```

预期能看到：

```text
generation_jobs
generation_records
```

`docker-compose.mysql.yml` 会把 `migrations/mysql/001_initial.sql` 挂载到 `/docker-entrypoint-initdb.d/001_initial.sql`。只有 `mysql-data` volume 第一次初始化时，MySQL 官方镜像才会执行该脚本。volume 已存在时，修改 `MYSQL_*` 环境变量不会重置密码、用户或旧数据。

阶段评估：正常。Compose 初始化适合新环境；已有 volume 的 schema 变更应通过 migration 脚本或 `scripts/init_mysql.py` 明确执行。

## 3. 本机 Python 初始化

如果 API/worker 运行在本机 Python，MySQL 运行在 Docker，连接地址使用 `127.0.0.1`：

```bash
uv pip install --python ./.venv/bin/python -r requirements-mysql.txt
DATABASE_URL='mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4' \
  ./.venv/bin/python scripts/init_mysql.py
```

本机运行时配置：

```env
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@127.0.0.1:3306/agent?charset=utf8mb4
```

Compose 容器内部运行时配置：

```env
DATABASE_BACKEND=mysql
DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4
```

阶段评估：正常。最常见错误是把本机 `127.0.0.1` 和容器内部 `mysql` 服务名混用。

## 4. 备份

创建本机备份目录：

```bash
mkdir -p backups/mysql
```

Compose MySQL 备份：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
  sh -c 'mysqldump --single-transaction --routines --triggers --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  > "backups/mysql/agent-$(date +%Y%m%d-%H%M%S).sql"
```

独立 `my-mysql` 容器备份：

```bash
docker exec my-mysql \
  sh -c 'mysqldump --single-transaction --routines --triggers --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  > "backups/mysql/agent-$(date +%Y%m%d-%H%M%S).sql"
```

检查备份文件：

```bash
ls -lh backups/mysql
head -n 20 backups/mysql/<backup-file>.sql
```

建议：

- 备份文件不要提交到 Git。
- 备份文件应和 `.env.runtime`、MySQL 密码、Chroma 数据分开保存。
- 生产环境应加密备份文件，并定期做恢复演练。
- MySQL 8 普通业务用户通常没有 `PROCESS` 权限，`mysqldump` 不加 `--no-tablespaces` 可能报 `Access denied; you need (at least one of) the PROCESS privilege(s)`。

阶段评估：正常。`mysqldump --single-transaction --no-tablespaces` 适合当前 InnoDB 表，能降低备份期间对写入的影响，并避免普通业务用户缺少 `PROCESS` 权限的问题。

## 5. 恢复到现有 Compose MySQL

恢复前先确认目标数据库和备份文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
  sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "select count(*) as records from generation_records; select count(*) as jobs from generation_jobs;"'
```

恢复：

```bash
cat backups/mysql/<backup-file>.sql | \
  docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec -T mysql \
    sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

恢复后检查：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
  sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "show tables; select count(*) as records from generation_records; select count(*) as jobs from generation_jobs;"'
```

注意：

- 恢复到已有数据库会覆盖同名表中的数据，执行前应先备份当前库。
- 如果目标库已有不兼容 schema，应先在临时环境恢复验证。
- 不要在不确认数据价值的情况下执行 `docker compose down -v`，它会删除 Compose volume。

阶段评估：有风险但可控。恢复操作会改变数据库状态，正式执行前必须先确认备份文件和目标环境。

## 6. 恢复演练到新 volume

推荐用独立 Compose project name 做恢复演练，避免影响当前运行环境：

```bash
COMPOSE_PROJECT_NAME=agent_restore_test \
  docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d mysql
```

恢复备份到演练库：

```bash
cat backups/mysql/<backup-file>.sql | \
  COMPOSE_PROJECT_NAME=agent_restore_test \
  docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec -T mysql \
    sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

检查演练库：

```bash
COMPOSE_PROJECT_NAME=agent_restore_test \
  docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
    sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "select count(*) as records from generation_records; select count(*) as jobs from generation_jobs;"'
```

演练完成后停止演练容器：

```bash
COMPOSE_PROJECT_NAME=agent_restore_test \
  docker compose -f docker-compose.yml -f docker-compose.mysql.yml down
```

如果确认不再需要演练 volume，再手动清理对应的 `agent_restore_test_mysql-data` volume。

阶段评估：正常。恢复演练应先在新 volume 做，确认备份可用后再考虑恢复到正式环境。

## 7. 已验证恢复演练

2026-06-24 已完成一次恢复演练：

- 备份源：`agent_mysql_smoke_mysql-data` volume。
- 备份文件：`/tmp/agent-mysql-backups/agent-smoke-20260624.sql`。
- 恢复目标：`agent_restore_test_mysql-data` volume。
- 恢复 project：`COMPOSE_PROJECT_NAME=agent_restore_test`。
- 验证结果：`generation_records=1`、`generation_jobs=1`。
- 验证 job：`df50848d423d45c69fcc817454955c72`，状态 `failed`，`record_id=8374573ace9c45afb80f88f6d9fd3bf1`。
- 验证 record：`8374573ace9c45afb80f88f6d9fd3bf1`，状态 `failed`，`gate_status=pending`。

演练过程中第一次使用普通业务用户执行 `mysqldump` 时遇到缺少 `PROCESS` 权限，已通过追加 `--no-tablespaces` 解决。演练结束后已停止并移除源库和恢复库临时容器及网络，没有执行 `-v`，两个 volume 均保留。

## 8. 运行检查

检查 API：

```bash
curl -sS http://127.0.0.1:8000/health
```

检查 MySQL 容器健康：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml ps mysql
```

检查应用是否写入 MySQL：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec mysql \
  sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "select id,status,record_id,created_at from generation_jobs order by created_at desc limit 5; select id,status,gate_status,created_at from generation_records order by created_at desc limit 5;"'
```

检查 API/worker 当前数据库配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml exec api \
  python -c "from app.core.config import Settings; s=Settings(); print(s.database_backend); print(s.database_url)"
```

阶段评估：正常。只要 API/worker 的 `DATABASE_BACKEND` 是 `mysql`，且 MySQL 表中有新任务或历史记录，就说明应用链路已切到 MySQL。

## 9. 常见问题

### 8.1 修改密码后仍无法登录

原因通常是 MySQL volume 已存在。`MYSQL_ROOT_PASSWORD`、`MYSQL_USER`、`MYSQL_PASSWORD` 只在首次初始化空 volume 时生效。已有数据需要用 MySQL 内部 SQL 修改用户密码，或在确认不要旧数据后换一个新的 volume。

### 8.2 本机能连，容器内连不上

本机 Python 使用 `127.0.0.1:3306`。Compose 容器内部使用 `mysql:3306`。容器内不要使用 `127.0.0.1` 连接 MySQL，否则会连到 API/worker 容器自己。

### 8.3 API 启动时报缺少 PyMySQL

MySQL backend 需要 `PyMySQL`。本机虚拟环境执行：

```bash
uv pip install --python ./.venv/bin/python -r requirements-mysql.txt
```

Compose 使用 `docker-compose.mysql.yml` 时会把镜像构建参数切到 `REQUIREMENTS_FILE=requirements-mysql.txt`。

### 8.4 初始化脚本没有执行

MySQL 官方镜像只在数据目录为空时执行 `/docker-entrypoint-initdb.d/`。如果 `mysql-data` volume 已存在，初始化脚本不会再次执行。可以用 `scripts/init_mysql.py` 显式初始化 schema，或新建演练 volume 验证初始化流程。

## 10. 下一步

MySQL 初始化、备份、恢复文档、一次恢复演练、完整 Compose API/worker 镜像 smoke 和 5 任务稳定性 smoke 已完成。

稳定性 smoke 结果：

- Redis/RQ + MySQL + API + worker 均由 Compose 启动。
- 连续提交 5 次预算门控异步任务，最终均为 `failed`，错误码均为 `budget_exceeded`。
- MySQL 写入 `generation_jobs=5` 和 `generation_records=5`，两表状态均为 `failed=5`。
- RQ `queue_count=0`、`failed_count=0`、`finished_count=5`。
- 重启 API/worker 后仍可查询最后一个 job 的失败状态和 `record_id`。

总评估：正常。MySQL backend 已具备可操作的初始化、备份和恢复流程，并已完成一次恢复演练、完整 Compose API/worker 镜像 smoke 和多任务稳定性 smoke；真正切生产默认前仍建议补 worker crash、Redis/MySQL 短暂不可用和更长时长运行验证。
