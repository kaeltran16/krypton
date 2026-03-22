import type { MLTrainRequest, MLTrainJob, MLTrainResult } from "../../shared/lib/api";

export type MLTab = "setup" | "training" | "results" | "history";

export interface DataReadiness {
  count: number;
  oldest: string | null;
  sufficient: boolean;
}

export type DataReadinessMap = Record<string, DataReadiness>;

export type LossHistoryEntry = NonNullable<MLTrainResult["loss_history"]>[number];

/** Job with extra metadata added at save-to-history time */
export interface MLTrainJobWithMeta extends MLTrainJob {
  preset_label?: string;
}

export type { MLTrainRequest, MLTrainJob };
