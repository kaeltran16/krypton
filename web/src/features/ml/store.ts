import { create } from "zustand";

interface BackfillStatus {
  job_id: string;
  status: string;
  progress?: Record<string, number>;
  result?: Record<string, number>;
  error?: string;
}

interface MLState {
  wsBackfillStatus: BackfillStatus | null;
  onBackfillUpdate: (data: BackfillStatus) => void;
}

export const useMLStore = create<MLState>((set) => ({
  wsBackfillStatus: null,
  onBackfillUpdate: (data) => set({ wsBackfillStatus: data }),
}));
