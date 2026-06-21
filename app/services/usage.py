import json
from math import ceil
from typing import Any

from app.core.config import Settings
from app.models.test_case import GenerationUsage


def estimate_generation_usage(
    settings: Settings,
    prompt_messages: list[list[dict[str, str]]],
    completion_payloads: list[Any],
) -> GenerationUsage:
    prompt_characters = sum(
        len(str(message.get("content", "")))
        for messages in prompt_messages
        for message in messages
    )
    completion_characters = sum(
        len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        for payload in completion_payloads
    )
    prompt_tokens = estimate_tokens(prompt_characters)
    completion_tokens = estimate_tokens(completion_characters)
    total_tokens = prompt_tokens + completion_tokens
    estimated_cost = _estimate_cost(
        settings,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return GenerationUsage(
        prompt_characters=prompt_characters,
        completion_characters=completion_characters,
        total_characters=prompt_characters + completion_characters,
        prompt_tokens_estimate=prompt_tokens,
        completion_tokens_estimate=completion_tokens,
        total_tokens_estimate=total_tokens,
        estimated_cost=estimated_cost,
        currency=settings.llm_cost_currency if estimated_cost is not None else None,
    )


def estimate_tokens(characters: int) -> int:
    if characters <= 0:
        return 0
    return ceil(characters / 2)


def _estimate_cost(
    settings: Settings,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    prompt_price = settings.llm_prompt_price_per_1k_tokens
    completion_price = settings.llm_completion_price_per_1k_tokens
    if prompt_price <= 0 and completion_price <= 0:
        return None
    cost = (prompt_tokens / 1000 * prompt_price) + (
        completion_tokens / 1000 * completion_price
    )
    return round(cost, 6)
