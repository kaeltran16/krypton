export interface HorizontalLevel {
  type: "level";
  pair: string;
  price: number;
  label: string;
  style: "solid" | "dashed";
  color: string;
  reasoning: string;
}

export interface Zone {
  type: "zone";
  pair: string;
  from_price: number;
  to_price: number;
  from_time?: number;
  to_time?: number;
  label: string;
  color: string;
  reasoning: string;
}

export interface SignalMarker {
  type: "signal";
  pair: string;
  time: number;
  price: number;
  direction: "long" | "short";
  label: string;
  reasoning: string;
}

export interface RegimeZone {
  type: "regime";
  pair: string;
  from_time: number;
  to_time: number;
  regime: "trending" | "ranging" | "volatile" | "steady";
  confidence: number;
  reasoning: string;
}

export interface TrendLine {
  type: "trendline";
  pair: string;
  from: { time: number; price: number };
  to: { time: number; price: number };
  label: string;
  color: string;
  reasoning: string;
}

export interface PositionMarker {
  type: "position";
  pair: string;
  entry_price: number;
  sl_price?: number;
  tp_price?: number;
  direction: "long" | "short";
  reasoning: string;
}

export type Annotation =
  | HorizontalLevel
  | Zone
  | SignalMarker
  | RegimeZone
  | TrendLine
  | PositionMarker;

export interface AgentAnalysis {
  id: number;
  type: "brief" | "pair_dive" | "signal_explain" | "position_check";
  pair: string | null;
  narrative: string;
  annotations: Annotation[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export type StalenessLevel = "fresh" | "aging" | "stale";

export function getStaleness(createdAt: string): StalenessLevel {
  const ageMs = Date.now() - new Date(createdAt).getTime();
  const hours = ageMs / (1000 * 60 * 60);
  if (hours < 4) return "fresh";
  if (hours < 24) return "aging";
  return "stale";
}

export function getAnnotationOpacity(staleness: StalenessLevel): number {
  if (staleness === "fresh") return 1;
  if (staleness === "aging") return 0.6;
  return 0.3;
}
