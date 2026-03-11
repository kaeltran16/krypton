import json
import logging
from pathlib import Path

import httpx

from app.engine.models import LLMResponse

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a decisive crypto futures trader with 10 years of experience. "
    "You trust quantitative signals and only override them when you see clear, "
    "specific evidence in the data — not vague concerns about volatility or risk. "
    "When indicators align, you confirm. You use caution only for concrete conflicts "
    "like bearish divergence on a long setup, or exhaustion candles at resistance. "
    "You contradict only when the data clearly says the trade will fail."
)


def load_prompt_template(path: Path) -> str:
    return path.read_text()


def render_prompt(template: str, **kwargs) -> str:
    return template.format(**kwargs)


async def call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> LLMResponse | None:
    """Call OpenRouter API and parse response into LLMResponse."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
        return parse_llm_response(content)
    except httpx.TimeoutException:
        logger.warning("OpenRouter request timed out")
        return None
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return None


def parse_llm_response(content: str) -> LLMResponse | None:
    """Parse LLM text response into structured LLMResponse."""
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return LLMResponse.model_validate(json.loads(text))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
