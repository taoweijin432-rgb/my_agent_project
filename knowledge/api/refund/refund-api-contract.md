# 订单退款 API 契约

## 创建退款申请

```http
POST /api/v1/refunds
```

请求字段：

- `order_id`：订单 ID，必填。
- `refund_type`：`full` 或 `partial`。
- `amount`：退款金额，单位元。
- `reason_code`：退款原因编码。
- `reason_detail`：退款说明。
- `return_tracking_no`：退货物流单号，已发货订单必填。
- `idempotency_key`：幂等键，客户端必传。

响应字段：

- `refund_id`：退款单 ID。
- `order_id`：订单 ID。
- `status`：`pending_review`、`approved`、`rejected`、`processing`、`succeeded`、`failed`。
- `review_mode`：`auto` 或 `manual`。
- `risk_flags`：命中的风控标签。
- `created_at`：申请创建时间。

错误约定：

- `400 invalid_refund_amount`：退款金额非法。
- `400 return_tracking_required`：已发货订单缺少退货物流单号。
- `409 refund_already_processing`：订单已经存在退款中申请。
- `409 idempotency_key_conflict`：幂等键对应的请求内容不一致。
- `422 order_status_not_refundable`：订单状态不允许退款。

## 查询退款详情

```http
GET /api/v1/refunds/{refund_id}
```

返回退款单状态、审核信息、支付渠道流水号、退款明细和失败原因。

## 审核退款申请

```http
POST /api/v1/refunds/{refund_id}/review
```

请求字段：

- `decision`：`approved` 或 `rejected`。
- `reviewer`：审核人。
- `comment`：审核备注。

约束：

- 只有 `pending_review` 状态允许审核。
- 人工拒绝必须填写 `comment`。
- 审核通过后异步调用支付渠道退款。

## 幂等要求

- 相同 `idempotency_key` 和相同请求体必须返回同一个 `refund_id`。
- 相同 `idempotency_key` 但请求体不同必须返回 `idempotency_key_conflict`。
- 支付渠道回调重复到达时不能重复更新退款明细。
