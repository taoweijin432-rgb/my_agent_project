# 登录模块原子验收矩阵

文档类型：acceptance_matrix
模块：login
用途：生成登录测试用例时的最小覆盖清单

## 使用规则

- 每一行都是一个原子验收点。
- 当 `max_cases` 允许时，每个原子验收点至少生成 1 条测试用例。
- 不要把 SQL 注入、暴力破解、账号枚举、token 泄露和审计日志合并成“通用安全防护”。
- 如果 `max_cases` 少于本矩阵条数，必须优先保留账号状态、密码边界、锁定、权限、安全和审计。
- 权限关键词必须保留：管理员、普通用户、管理首页、用户管理入口。
- deleted 用户关键词必须保留：通用失败提示、不能暴露账号是否存在、不签发任何 token。

| ID | 原子场景 | 推荐 type | 必须断言 |
| --- | --- | --- | --- |
| AC-LOGIN-001 | active 用户账号密码登录成功 | functional | 登录成功，返回 `access_token` 和 `refresh_token` |
| AC-LOGIN-002 | disabled 用户登录失败 | exception | 提示账号已禁用，不签发任何 token |
| AC-LOGIN-003 | deleted 用户登录失败 | exception | 返回通用失败提示，不能暴露账号是否存在，不签发任何 token |
| AC-LOGIN-004 | 密码长度 7 位 | boundary | 登录失败，提示密码格式错误或输入不合法 |
| AC-LOGIN-005 | 密码长度 8 位 | boundary | 密码格式校验通过 |
| AC-LOGIN-006 | 密码长度 32 位 | boundary | 密码格式校验通过 |
| AC-LOGIN-007 | 密码长度 33 位 | boundary | 登录失败，提示密码格式错误或输入不合法 |
| AC-LOGIN-008 | 连续 5 次密码错误 | exception | 账号锁定 15 分钟 |
| AC-LOGIN-009 | 锁定期间输入正确密码 | exception | 登录失败，不签发 token，提示账号锁定或稍后再试 |
| AC-LOGIN-010 | 验证码错误 | exception | 不累计密码错误次数 |
| AC-LOGIN-011 | 连续 3 次密码错误后再次登录 | exception | 触发二次短信验证码校验 |
| AC-LOGIN-012 | access_token 有效期 | functional | `access_token` 有效期为 2 小时 |
| AC-LOGIN-013 | refresh_token 有效期 | functional | `refresh_token` 有效期为 7 天 |
| AC-LOGIN-014 | 管理员登录 | permission | 进入管理首页，可以看到用户管理入口 |
| AC-LOGIN-015 | 普通用户登录 | permission | 进入普通首页，不能进入管理首页，不能看到用户管理入口 |
| AC-LOGIN-016 | SQL 注入防护 | security | 注入 payload 不能绕过认证，数据库不能执行注入语句 |
| AC-LOGIN-017 | 暴力破解防护 | security | 高频密码错误会触发锁定或限制，不能无限尝试 |
| AC-LOGIN-018 | 账号枚举防护 | security | 账号不存在和密码错误返回通用失败提示，不能区分具体原因 |
| AC-LOGIN-019 | token 泄露防护 | security | token 不出现在 URL、应用日志、错误提示或审计明文中 |
| AC-LOGIN-020 | 审计日志字段 | functional | 审计日志包含 `user_id`、`ip`、`user_agent`、`result`、`reason`、`created_at` |

## 不可合并场景

以下场景必须独立表达，不要合并成一个泛化用例：

- disabled 用户登录失败。
- deleted 用户登录失败且不能暴露账号是否存在。
- SQL 注入防护。
- 暴力破解防护。
- 账号枚举防护。
- token 泄露防护。
- 审计日志字段校验。
