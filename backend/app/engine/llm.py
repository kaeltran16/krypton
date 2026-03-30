import asyncio
import json
import logging
from pathlib import Path

import httpx

from app.engine.models import LLMResponse, LLMResult

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a decisive crypto futures trader with 10 years of experience. "
    "You analyze quantitative data and identify specific factors that support "
    "or undermine a trade setup. You focus on concrete evidence — divergences, "
    "key levels, exhaustion signals, positioning extremes. "
    "Apply equal scrutiny to both long and short setups."
)

DEVILS_ADVOCATE_SYSTEM_PROMPT = (
    "You are a critical analyst reviewing a crypto futures trade setup. "
    "Your task is to identify the strongest case AGAINST the prevailing signal "
    "direction. Score the top 3-5 factors that support the opposing view. "
    "Focus on concrete evidence — divergences, overextension, exhaustion signals, "
    "positioning extremes, key levels. Be genuinely contrarian."
)

MAX_FACTORS = 5


def load_prompt_template(path: Path) -> str:
    return path.read_text()


def render_prompt(template: str, **kwargs) -> str:
    return template.format(**kwargs)


async def call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
    system_prompt: str = SYSTEM_PROMPT,
) -> LLMResult | None:
    """Call OpenRouter API and parse response into LLMResult with token usage."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 1000,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        parsed = parse_llm_response(content)
        if parsed is None:
            return None

        usage = data.get("usage", {})
        return LLMResult(
            response=parsed,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", model),
        )
    except httpx.TimeoutException:
        logger.warning("OpenRouter request timed out")
        return None
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return None


async def call_openrouter_dual_pass(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> tuple[LLMResult | None, LLMResult | None]:
    """Call OpenRouter twice concurrently: standard + devil's advocate.

    Returns (standard_result, devils_result). Either may be None on failure.
    """
    results = await asyncio.gather(
        call_openrouter(prompt, api_key, model, timeout, system_prompt=SYSTEM_PROMPT),
        call_openrouter(prompt, api_key, model, timeout, system_prompt=DEVILS_ADVOCATE_SYSTEM_PROMPT),
        return_exceptions=True,
    )
    standard = results[0] if not isinstance(results[0], BaseException) else None
    devils = results[1] if not isinstance(results[1], BaseException) else None
    return standard, devils


def parse_llm_response(content: str) -> LLMResponse | None:
    """Parse LLM text response into structured LLMResponse with factors."""
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(text)

        # Truncate to max factors before validation
        if "factors" in data and isinstance(data["factors"], list):
            data["factors"] = data["factors"][:MAX_FACTORS]

        parsed = LLMResponse.model_validate(data)

        if not parsed.factors:
            logger.error("LLM returned empty factors list")
            return None

        return parsed
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
