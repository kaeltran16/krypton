export type Direction = "LONG" | "SHORT";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type LlmOpinion = "confirm" | "caution" | "contradict";
export type Timeframe = "15m" | "1h" | "4h";

export interface SignalLevels {
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
}

export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  confidence: Confidence;
  traditional_score: number;
  llm_opinion: LlmOpinion | null;
  explanation: string | null;
  levels: SignalLevels;
  created_at: string;
}
