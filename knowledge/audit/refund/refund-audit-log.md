# 订单退款审计日志

## 日志事件

退款模块必须记录以下事件：

- `refund_created`：退款申请创建。
- `refund_reviewed`：退款审核完成。
- `refund_risk_flagged`：退款命中风控标签。
- `refund_payment_requested`：调用支付渠道退款。
- `refund_payment_callback`：收到支付渠道回调。
- `refund_succeeded`：退款成功。
- `refund_failed`：退款失败。

## 必填字段

- `refund_id`
- `order_id`
- `user_id`
- `operator`
- `event`
- `before_status`
- `after_status`
- `amount`
- `review_mode`
- `risk_flags`
- `payment_channel`
- `payment_refund_no`
- `request_id`
- `created_at`

## 脱敏要求

- 审计日志不能记录完整银行卡号、身份证号或支付账户。
- `reason_detail` 如果包含手机号，需要脱敏为 `138****0000` 格式。
- 支付渠道原始回调只保存摘要和验签结果，不能保存完整敏感报文。

## 验收点

- 每次状态变更必须有一条审计日志。
- 支付渠道重复回调必须记录回调事件，但不能重复生成退款成功事件。
- 风控标签和审核人必须能从审计日志追溯。
