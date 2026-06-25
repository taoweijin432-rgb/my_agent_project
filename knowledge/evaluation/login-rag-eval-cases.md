# 登录模块 RAG 评估集

文档类型：rag_eval_cases
模块：login
用途：知识库变更后，用于检查 RAG 召回和生成覆盖是否稳定。

## 评估规则

- 每条 query 都应命中对应 `expected_sources`。
- 命中 chunk 中必须包含 `expected_keywords` 的主要关键词。
- 生成测试用例时，必须覆盖 `expected_acceptance_points`。

## Case 1：账号状态

query: 登录 active disabled deleted 用户状态

expected_sources:

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- active
- disabled
- deleted
- 不签发任何 token
- 不能暴露账号是否存在

expected_acceptance_points:

- active 用户登录成功。
- disabled 用户登录失败并提示账号已禁用。
- deleted 用户登录失败并返回通用失败提示。

## Case 2：密码边界和锁定

query: 登录 密码长度 7 8 32 33 连续 5 次错误 锁定 15 分钟

expected_sources:

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- 7 位
- 8 位
- 32 位
- 33 位
- 5 次
- 15 分钟

expected_acceptance_points:

- 密码长度 7 位失败。
- 密码长度 8 位格式通过。
- 密码长度 32 位格式通过。
- 密码长度 33 位失败。
- 连续 5 次密码错误锁定 15 分钟。
- 锁定期间正确密码仍登录失败。

## Case 3：验证码

query: 登录 验证码错误 不累计密码错误次数 二次短信验证码

expected_sources:

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- 验证码错误
- 不累计密码错误次数
- 连续 3 次密码错误
- 二次短信验证码

expected_acceptance_points:

- 验证码错误不累计密码错误次数。
- 连续 3 次密码错误后再次登录触发二次短信验证码。

## Case 4：token

query: 登录 access_token refresh_token 有效期 token 泄露

expected_sources:

- `knowledge/prd/login/login-prd.md`
- `knowledge/api/login/login-api-contract.md`
- `knowledge/security/login/login-security-baseline.md`

expected_keywords:

- access_token
- refresh_token
- 2 小时
- 7 天
- token 不出现在 URL
- token 不写入应用日志

expected_acceptance_points:

- `access_token` 有效期为 2 小时。
- `refresh_token` 有效期为 7 天。
- token 不出现在 URL、应用日志、错误提示或审计明文中。

## Case 5：权限

query: 登录 管理员 普通用户 管理首页 用户管理入口

expected_sources:

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- 管理员
- 普通用户
- 管理首页
- 用户管理入口

expected_acceptance_points:

- 管理员进入管理首页并看到用户管理入口。
- 普通用户进入普通首页，不能进入管理首页，不能看到用户管理入口。

## Case 6：安全

query: 登录 SQL 注入 暴力破解 账号枚举

expected_sources:

- `knowledge/security/login/login-security-baseline.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- SQL 注入
- 暴力破解
- 账号枚举
- 通用登录失败提示
- 不能无限尝试

expected_acceptance_points:

- SQL 注入 payload 不能绕过认证。
- 暴力破解或高频密码错误会触发锁定或限制。
- 账号不存在和密码错误返回通用失败提示。

## Case 7：审计日志

query: 登录 审计日志 user_id ip user_agent result reason created_at

expected_sources:

- `knowledge/audit/login/login-audit-log.md`
- `knowledge/prd/login/login-acceptance-matrix.md`

expected_keywords:

- user_id
- ip
- user_agent
- result
- reason
- created_at

expected_acceptance_points:

- 登录成功写审计日志。
- 登录失败写审计日志。
- 账号锁定写审计日志。
- 二次短信验证码触发写审计日志。
- 审计日志包含 `user_id`、`ip`、`user_agent`、`result`、`reason`、`created_at`。
