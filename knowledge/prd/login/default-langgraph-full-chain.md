# 登录模块知识库索引

文档用途：登录模块 RAG 知识库总览。生成测试用例时，优先检索并使用下列拆分文档中的原子验收点，不要只依赖本索引。

## 推荐导入 source

- `knowledge/prd/login/login-prd.md`
- `knowledge/prd/login/login-acceptance-matrix.md`
- `knowledge/api/login/login-api-contract.md`
- `knowledge/security/login/login-security-baseline.md`
- `knowledge/audit/login/login-audit-log.md`
- `knowledge/evaluation/login-rag-eval-cases.md`

## 模块范围

登录模块支持账号密码登录。账号可以是用户名或邮箱。密码长度为 8 到 32 位。登录成功后返回 `access_token` 和 `refresh_token`，并根据角色进入对应首页。

## 核心不可漏测点

- active、disabled、deleted 三类账号状态。
- 密码长度 7、8、32、33 位边界。
- 连续 5 次密码错误锁定 15 分钟。
- 锁定期间正确密码仍不能登录。
- 验证码错误不累计密码错误次数。
- 连续 3 次密码错误触发二次短信验证码。
- `access_token` 有效期 2 小时。
- `refresh_token` 有效期 7 天。
- 管理员和普通用户权限跳转。
- SQL 注入、暴力破解、账号枚举、token 泄露。
- 登录成功、失败、锁定、二次验证码触发的审计日志。

## 生成要求

当用户要求生成登录测试用例时：

- 优先使用 `login-acceptance-matrix.md` 中的原子验收点。
- 安全场景必须参考 `login-security-baseline.md`，不得合并成“通用安全防护”。
- 审计场景必须参考 `login-audit-log.md`，必须校验审计字段。
- API 字段、错误码和响应断言必须参考 `login-api-contract.md`。
- 如果 `max_cases` 小于矩阵场景数，必须优先保留账号状态、密码边界、锁定、权限、安全和审计。
