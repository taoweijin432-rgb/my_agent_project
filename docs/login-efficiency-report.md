# AI Test Case Generation Efficiency Report

## Time

- Manual baseline: 35.0 minutes
- AI generation and review: 0.85 minutes
- AI time source: measured_generate
- Case source: live_generation
- Saved time: 34.15 minutes
- Time reduction rate: 97.56%

## Requirement Coverage

- Requirements: 3/6
- Coverage rate: 50.00%
- Keyword coverage rate: 87.50%

| Requirement | Covered | Score | Matched Cases | Missing Keywords |
| --- | --- | ---: | --- | --- |
| REQ-LOGIN-001 有效手机号和验证码登录成功 | no | 66.67% | TC-001 | 有效验证码 |
| REQ-LOGIN-002 验证码 5 分钟有效期 | yes | 100.00% | TC-001, TC-003 |  |
| REQ-LOGIN-003 连续错误触发锁定 | yes | 100.00% | TC-004 |  |
| REQ-LOGIN-004 disabled 用户禁止登录 | no | 75.00% | TC-005 | 不能登录 |
| REQ-LOGIN-005 token 泄露防护 | no | 75.00% | TC-005, TC-006 | 不写入应用日志 |
| REQ-LOGIN-006 审计日志字段完整 | yes | 100.00% | TC-001, TC-002, TC-003, TC-004, TC-005, TC-006 |  |
