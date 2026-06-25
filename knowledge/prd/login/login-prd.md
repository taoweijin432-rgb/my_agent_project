# 登录模块 PRD

文档类型：PRD
模块：login
适用场景：账号密码登录测试用例生成

## 1. 目标

用户可以使用用户名或邮箱加密码登录系统。系统必须根据账号状态、密码规则、锁定规则、角色权限和安全策略返回明确、可验证的结果。

## 2. 功能范围

- 支持用户名登录。
- 支持邮箱登录。
- 支持账号密码登录成功后签发 `access_token` 和 `refresh_token`。
- 支持管理员和普通用户登录后跳转到不同首页。
- 支持密码错误计数、账号锁定和二次短信验证码触发。
- 支持登录相关审计日志。

## 3. 非目标

- 本文档不覆盖手机号验证码登录。
- 本文档不覆盖第三方 OAuth 登录。
- 本文档不覆盖找回密码、注册、修改密码。
- 本文档不覆盖前端样式和国际化。

## 4. 账号状态规则

### AC-LOGIN-STATE-001 active 用户登录成功

- type: functional
- Given 用户状态为 active，账号存在，密码正确
- When 用户提交用户名或邮箱和正确密码
- Then 登录成功
- Then 返回 `access_token`
- Then 返回 `refresh_token`
- Then 根据用户角色跳转到对应首页

### AC-LOGIN-STATE-002 disabled 用户禁止登录

- type: exception
- Given 用户状态为 disabled
- When 用户提交正确账号和正确密码
- Then 登录失败
- Then 提示账号已禁用
- Then 不签发 `access_token`
- Then 不签发 `refresh_token`

### AC-LOGIN-STATE-003 deleted 用户禁止登录且不暴露账号存在性

- type: exception
- Given 用户状态为 deleted
- When 用户提交正确账号和正确密码
- Then 登录失败
- Then 不签发任何 token
- Then 返回通用登录失败提示
- Then 不能暴露账号是否存在

## 5. 密码规则

### AC-LOGIN-PWD-001 密码长度少于 8 位

- type: boundary
- Given 用户输入密码长度为 7 位
- When 用户提交登录
- Then 登录失败
- Then 提示密码格式错误或输入不合法

### AC-LOGIN-PWD-002 密码长度等于 8 位

- type: boundary
- Given 用户输入密码长度为 8 位
- When 用户提交登录
- Then 密码格式校验通过
- Then 后续按账号状态和密码正确性判断登录结果

### AC-LOGIN-PWD-003 密码长度等于 32 位

- type: boundary
- Given 用户输入密码长度为 32 位
- When 用户提交登录
- Then 密码格式校验通过
- Then 后续按账号状态和密码正确性判断登录结果

### AC-LOGIN-PWD-004 密码长度大于 32 位

- type: boundary
- Given 用户输入密码长度为 33 位
- When 用户提交登录
- Then 登录失败
- Then 提示密码格式错误或输入不合法

## 6. 错误次数、锁定和验证码

### AC-LOGIN-LOCK-001 连续 5 次密码错误后锁定

- type: exception
- Given active 用户连续输入错误密码
- When 同一账号连续第 5 次密码错误
- Then 账号被锁定 15 分钟
- Then 登录失败
- Then 返回账号锁定或稍后再试提示

### AC-LOGIN-LOCK-002 锁定期间正确密码仍失败

- type: exception
- Given 账号处于 15 分钟锁定期内
- When 用户输入正确密码
- Then 登录失败
- Then 不签发 token
- Then 提示账号锁定或稍后再试

### AC-LOGIN-CAPTCHA-001 验证码错误不累计密码错误次数

- type: exception
- Given 用户触发验证码校验
- When 用户输入错误验证码
- Then 登录失败
- Then 提示验证码错误
- Then 不增加密码错误次数

### AC-LOGIN-CAPTCHA-002 连续 3 次密码错误触发二次短信验证码

- type: exception
- Given active 用户连续输入错误密码
- When 同一账号连续第 3 次密码错误后再次登录
- Then 必须触发二次短信验证码校验
- Then 发送或要求输入短信验证码

## 7. Token 规则

### AC-LOGIN-TOKEN-001 access_token 有效期

- type: functional
- Given 用户登录成功
- When 系统签发 `access_token`
- Then `access_token` 有效期为 2 小时

### AC-LOGIN-TOKEN-002 refresh_token 有效期

- type: functional
- Given 用户登录成功
- When 系统签发 `refresh_token`
- Then `refresh_token` 有效期为 7 天

## 8. 权限和跳转

### AC-LOGIN-PERM-001 管理员登录进入管理首页

- type: permission
- Given 用户角色为管理员
- When 管理员登录成功
- Then 进入管理首页
- Then 可以看到用户管理入口

### AC-LOGIN-PERM-002 普通用户不能访问管理功能

- type: permission
- Given 用户角色为普通用户
- When 普通用户登录成功
- Then 进入普通首页
- Then 不能进入管理首页
- Then 不能看到用户管理入口
