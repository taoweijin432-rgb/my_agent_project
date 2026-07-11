# 订单退款风控规则

## 风控触发条件

- 单笔退款金额超过 5000 元，标记 `large_amount_refund`。
- 同一用户 24 小时内超过 3 笔退款申请，标记 `frequent_refund_user`。
- 同一收货地址 24 小时内超过 5 笔退款申请，标记 `address_refund_cluster`。
- 命中黑名单用户，标记 `blacklisted_user`。
- 退款原因与订单履约状态冲突，标记 `reason_status_mismatch`。

## 风控处理

- 命中任一风控标签时，`review_mode` 必须为 `manual`。
- 命中 `blacklisted_user` 时，不能自动通过审核。
- 命中 `large_amount_refund` 时，需要二级审核人复核。
- 命中 `frequent_refund_user` 时，需要展示最近 24 小时退款次数和订单列表。

## 测试关注点

- 4999.99 元不触发 `large_amount_refund`，5000.01 元触发。
- 第 3 笔退款不触发 `frequent_refund_user`，第 4 笔触发。
- 黑名单用户即使订单未发货也不能自动退款。
- 风控标签必须写入退款详情和审计日志。
