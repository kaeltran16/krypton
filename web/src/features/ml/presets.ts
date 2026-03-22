import type { MLTrainRequest } from "../../shared/lib/api";

export type PresetName = "quick" | "balanced" | "production";

export interface Preset {
  name: PresetName;
  label: string;
  config: Partial<MLTrainRequest>;
}

export const PRESETS: Preset[] = [
  {
    name: "quick",
    label: "Quick Test",
    config: {
      epochs: 30,
      batch_size: 32,
      hidden_size: 64,
      num_layers: 1,
      seq_len: 25,
      dropout: 0.2,
      lr: 0.003,
    },
  },
  {
    name: "balanced",
    label: "Balanced",
    config: {
      epochs: 100,
      batch_size: 64,
      hidden_size: 128,
      num_layers: 2,
      seq_len: 50,
      dropout: 0.3,
      lr: 0.001,
    },
  },
  {
    name: "production",
    label: "Production",
    config: {
      epochs: 300,
      batch_size: 128,
      hidden_size: 256,
      num_layers: 3,
      seq_len: 100,
      dropout: 0.3,
      lr: 0.0005,
    },
  },
];

export const DEFAULT_CONFIG: MLTrainRequest = {
  timeframe: "1h",
  lookback_days: 365,
  label_horizon: 24,
  label_threshold_pct: 1.5,
  ...PRESETS[1].config, // Balanced defaults
};

/** Candles per day for each timeframe — used for backfill progress estimation */
export const CANDLES_PER_DAY: Record<string, number> = {
  "15m": 96,
  "1h": 24,
  "4h": 6,
};
