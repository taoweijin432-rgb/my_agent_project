# 登录接口契约

文档类型：api_contract
模块：login
接口：`POST /api/v1/auth/login`

## 1. 请求体

```json
{
  "account": "string",
  "password": "string",
  "captcha_code": "string|null",
  "sms_code": "string|null"
}
```

## 2. 字段规则

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `account` | 是 | 用户名或邮箱，不能为空 |
| `password` | 是 | 8 到 32 位 |
| `captcha_code` | 否 | 触发验证码校验时必填 |
| `sms_code` | 否 | 触发二次短信验证码时必填 |

## 3. 成功响应

```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "Bearer",
  "expires_in": 7200,
  "refresh_expires_in": 604800,
  "redirect": "/home|/admin"
}
```

必须断言：

- HTTP 状态码为 200。
- `access_token` 存在。
- `refresh_token` 存在。
- `expires_in` 等于 7200 秒，即 2 小时。
- `refresh_expires_in` 等于 604800 秒，即 7 天。
- 管理员 `redirect` 为 `/admin` 或管理首页等价地址。
- 普通用户 `redirect` 为 `/home` 或普通首页等价地址。

## 4. 失败响应

```json
{
  "code": "LOGIN_FAILED|ACCOUNT_DISABLED|ACCOUNT_LOCKED|PASSWORD_FORMAT_INVALID|CAPTCHA_INVALID|SMS_CODE_REQUIRED",
  "message": "string"
}
```

## 5. 错误码断言

| 场景 | HTTP 状态 | code | 必须断言 |
| --- | --- | --- | --- |
| 账号不存在 | 401 | `LOGIN_FAILED` | 返回通用登录失败提示，不能暴露账号不存在 |
| 密码错误 | 401 | `LOGIN_FAILED` | 返回通用登录失败提示，不能暴露具体原因 |
| disabled 用户 | 403 | `ACCOUNT_DISABLED` | 提示账号已禁用，不签发 token |
| deleted 用户 | 401 | `LOGIN_FAILED` | 返回通用登录失败提示，不签发 token |
| 密码长度非法 | 400 | `PASSWORD_FORMAT_INVALID` | 提示密码格式错误或输入不合法 |
| 账号锁定 | 423 | `ACCOUNT_LOCKED` | 提示账号锁定或稍后再试 |
| 验证码错误 | 400 | `CAPTCHA_INVALID` | 不累计密码错误次数 |
| 需要二次短信验证码 | 428 | `SMS_CODE_REQUIRED` | 触发二次短信验证码校验 |

## 6. 安全响应约束

- 失败响应不得包含明文密码。
- 失败响应不得包含 `access_token`。
- 失败响应不得包含 `refresh_token`。
- token 不得出现在 URL query 参数。
- 账号不存在和密码错误的 `message` 必须保持同类通用提示，避免账号枚举。
