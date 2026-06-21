from app.core.config import Settings
from app.services.usage import estimate_generation_usage, estimate_tokens


def test_estimate_tokens_uses_local_character_heuristic() -> None:
    assert estimate_tokens(0) == 0
    assert estimate_tokens(1) == 1
    assert estimate_tokens(4) == 2
    assert estimate_tokens(5) == 3


def test_estimate_generation_usage_counts_prompt_and_completion() -> None:
    usage = estimate_generation_usage(
        Settings(
            llm_prompt_price_per_1k_tokens=0.01,
            llm_completion_price_per_1k_tokens=0.02,
            llm_cost_currency="CNY",
        ),
        prompt_messages=[
            [
                {"role": "system", "content": "abcd"},
                {"role": "user", "content": "需求"},
            ]
        ],
        completion_payloads=[{"cases": [{"title": "登录成功"}]}],
    )

    assert usage.prompt_characters == 6
    assert usage.completion_characters > 0
    assert usage.total_characters == usage.prompt_characters + usage.completion_characters
    assert usage.prompt_tokens_estimate == 3
    assert usage.completion_tokens_estimate > 0
    assert usage.total_tokens_estimate == (
        usage.prompt_tokens_estimate + usage.completion_tokens_estimate
    )
    assert usage.estimated_cost is not None
    assert usage.currency == "CNY"


def test_estimate_generation_usage_omits_cost_when_prices_are_not_configured() -> None:
    usage = estimate_generation_usage(
        Settings(),
        prompt_messages=[[{"role": "user", "content": "需求"}]],
        completion_payloads=[],
    )

    assert usage.estimated_cost is None
    assert usage.currency is None
