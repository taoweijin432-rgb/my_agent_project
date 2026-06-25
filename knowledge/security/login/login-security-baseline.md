# 登录安全基线

文档类型：security_baseline
模块：login

## 1. 使用规则

生成登录安全测试用例时，以下风险必须独立覆盖。不要把它们合并为“通用安全防护”。

## 2. SQL 注入

### SEC-LOGIN-001 SQL 注入不能绕过认证

- type: security
- Given 攻击者在 `account` 或 `password` 中输入 SQL 注入 payload
- When 调用登录接口
- Then 登录失败
- Then 数据库不能执行注入语句
- Then 不能绕过认证
- Then 响应不包含数据库错误堆栈

推荐 payload：

- `' OR '1'='1`
- `admin' --`
- `'; DROP TABLE users; --`

## 3. 暴力破解

### SEC-LOGIN-002 高频密码错误触发限制

- type: security
- Given 同一账号或同一 IP 高频提交错误密码
- When 密码错误达到限制阈值
- Then 账号锁定 15 分钟或触发等价限制
- Then 不能无限尝试密码
- Then 锁定期间正确密码仍登录失败

## 4. 账号枚举

### SEC-LOGIN-003 账号不存在和密码错误不可区分

- type: security
- Given 一个不存在账号和一个存在账号但密码错误
- When 分别提交登录
- Then 两种响应都使用通用登录失败提示
- Then 响应不能区分账号不存在和密码错误
- Then 响应时间不应暴露明显差异

## 5. token 泄露

### SEC-LOGIN-004 token 不得泄露

- type: security
- Given 用户登录成功或登录失败
- When 检查 URL、应用日志、错误提示和审计日志
- Then token 不出现在 URL
- Then token 不写入应用日志
- Then token 不出现在错误提示
- Then token 不以明文写入审计日志

## 6. 敏感字段

以下字段禁止出现在日志、错误提示和审计明文中：

- 明文密码。
- `access_token` 明文。
- `refresh_token` 明文。
- 短信验证码明文。
