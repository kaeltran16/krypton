from typing import Literal

from pydantic import BaseModel

Opinion = Literal["confirm", "caution", "contradict"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
Direction = Literal["LONG", "SHORT"]


class LLMLevels(BaseModel):
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float


class LLMResponse(BaseModel):
    opinion: Opinion
    confidence: Confidence
    explanation: str
    levels: LLMLevels | None = None


class SignalResult(BaseModel):
    pair: str
    timeframe: str
    direction: Direction
    final_score: int
    traditional_score: int
    llm_opinion: Opinion | None = None
    llm_confidence: Confidence | None = None
    explanation: str | None = None
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    raw_indicators: dict
