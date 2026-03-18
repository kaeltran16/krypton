from enum import Enum
from typing import Literal

from pydantic import BaseModel

Direction = Literal["LONG", "SHORT"]


class FactorCategory(str, Enum):
    STRUCTURE = "structure"
    MOMENTUM = "momentum"
    EXHAUSTION = "exhaustion"
    EVENT = "event"


class FactorType(str, Enum):
    SUPPORT_PROXIMITY = "support_proximity"
    RESISTANCE_PROXIMITY = "resistance_proximity"
    LEVEL_BREAKOUT = "level_breakout"
    HTF_ALIGNMENT = "htf_alignment"
    RSI_DIVERGENCE = "rsi_divergence"
    VOLUME_DIVERGENCE = "volume_divergence"
    MACD_DIVERGENCE = "macd_divergence"
    VOLUME_EXHAUSTION = "volume_exhaustion"
    FUNDING_EXTREME = "funding_extreme"
    CROWDED_POSITIONING = "crowded_positioning"
    PATTERN_CONFIRMATION = "pattern_confirmation"
    NEWS_CATALYST = "news_catalyst"


FACTOR_CATEGORIES: dict[FactorType, FactorCategory] = {
    FactorType.SUPPORT_PROXIMITY: FactorCategory.STRUCTURE,
    FactorType.RESISTANCE_PROXIMITY: FactorCategory.STRUCTURE,
    FactorType.LEVEL_BREAKOUT: FactorCategory.STRUCTURE,
    FactorType.HTF_ALIGNMENT: FactorCategory.STRUCTURE,
    FactorType.RSI_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.VOLUME_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.MACD_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.VOLUME_EXHAUSTION: FactorCategory.EXHAUSTION,
    FactorType.FUNDING_EXTREME: FactorCategory.EXHAUSTION,
    FactorType.CROWDED_POSITIONING: FactorCategory.EXHAUSTION,
    FactorType.PATTERN_CONFIRMATION: FactorCategory.EVENT,
    FactorType.NEWS_CATALYST: FactorCategory.EVENT,
}

DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "support_proximity": 6.0,
    "resistance_proximity": 6.0,
    "level_breakout": 8.0,
    "htf_alignment": 7.0,
    "rsi_divergence": 7.0,
    "volume_divergence": 6.0,
    "macd_divergence": 6.0,
    "volume_exhaustion": 5.0,
    "funding_extreme": 5.0,
    "crowded_positioning": 5.0,
    "pattern_confirmation": 5.0,
    "news_catalyst": 7.0,
}


class LLMLevels(BaseModel):
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float


class LLMFactor(BaseModel):
    type: FactorType
    direction: Literal["bullish", "bearish"]
    strength: Literal[1, 2, 3]
    reason: str


class LLMResponse(BaseModel):
    factors: list[LLMFactor]
    explanation: str
    levels: LLMLevels | None = None


class LLMResult(BaseModel):
    response: LLMResponse
    prompt_tokens: int
    completion_tokens: int
    model: str


class SignalResult(BaseModel):
    pair: str
    timeframe: str
    direction: Direction
    final_score: int
    traditional_score: int
    explanation: str | None = None
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    raw_indicators: dict
