# 登录审计日志要求

文档类型：audit_spec
模块：login

## 1. 必须记录的事件

以下事件必须写审计日志：

- 登录成功。
- 登录失败。
- 账号锁定。
- 二次短信验证码触发。

## 2. 审计字段

每条登录审计日志必须包含：

| 字段 | 说明 | 必须断言 |
| --- | --- | --- |
| `user_id` | 用户 ID；账号不存在时可为空或使用匿名标识 | 字段存在 |
| `ip` | 客户端 IP | 字段存在 |
| `user_agent` | 客户端 UA | 字段存在 |
| `result` | `success` 或 `failed` | 字段存在且取值正确 |
| `reason` | 成功、密码错误、账号禁用、账号锁定、需要短信验证码等原因 | 字段存在且和事件一致 |
| `created_at` | 审计日志创建时间 | 字段存在且为合法时间 |

## 3. 事件级验收点

### AUDIT-LOGIN-001 登录成功日志

- type: functional
- Given active 用户登录成功
- When 系统写入审计日志
- Then 审计日志包含 `user_id`、`ip`、`user_agent`、`result`、`reason`、`created_at`
- Then `result=success`

### AUDIT-LOGIN-002 登录失败日志

- type: functional
- Given 用户登录失败
- When 系统写入审计日志
- Then 审计日志包含 `user_id`、`ip`、`user_agent`、`result`、`reason`、`created_at`
- Then `result=failed`
- Then `reason` 能体现失败原因类别

### AUDIT-LOGIN-003 账号锁定日志

- type: functional
- Given 用户连续 5 次密码错误导致账号锁定
- When 系统写入审计日志
- Then 审计日志包含锁定事件
- Then `reason` 体现账号锁定

### AUDIT-LOGIN-004 二次短信验证码触发日志

- type: functional
- Given 用户连续 3 次密码错误后再次登录
- When 系统触发二次短信验证码
- Then 审计日志包含二次短信验证码触发事件
- Then `reason` 体现二次短信验证码

## 4. 禁止记录

审计日志禁止记录：

- 明文密码。
- 明文 `access_token`。
- 明文 `refresh_token`。
- 明文短信验证码。
