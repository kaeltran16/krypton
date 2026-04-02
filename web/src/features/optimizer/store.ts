import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { OptimizerStatus, Proposal } from "./types";

const wait = (ms: number) => new Promise<void>((resolve) => {
  setTimeout(resolve, ms);
});

interface OptimizerStore {
  status: OptimizerStatus | null;
  proposals: Proposal[];
  loading: boolean;
  actionLoading: boolean;
  signalOptLoading: boolean;
  error: string | null;

  fetchStatus: () => Promise<void>;
  fetchProposals: () => Promise<void>;
  approve: (id: number) => Promise<void>;
  reject: (id: number, reason?: string) => Promise<void>;
  promote: (id: number) => Promise<void>;
  rollback: (id: number) => Promise<void>;
  optimizeFromSignals: (pair: string) => Promise<void>;
}

export const useOptimizerStore = create<OptimizerStore>((set, get) => ({
  status: null,
  proposals: [],
  loading: false,
  actionLoading: false,
  signalOptLoading: false,
  error: null,

  fetchStatus: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getOptimizerStatus();
      set({ status: data, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  fetchProposals: async () => {
    try {
      const data = await api.getOptimizerProposals({ limit: 50 });
      set({ proposals: data.proposals });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  approve: async (id) => {
    set({ actionLoading: true });
    try {
      await api.approveProposal(id);
      await Promise.all([get().fetchStatus(), get().fetchProposals()]);
    } finally {
      set({ actionLoading: false });
    }
  },

  reject: async (id, reason) => {
    set({ actionLoading: true });
    try {
      await api.rejectProposal(id, reason);
      await Promise.all([get().fetchStatus(), get().fetchProposals()]);
    } finally {
      set({ actionLoading: false });
    }
  },

  promote: async (id) => {
    set({ actionLoading: true });
    try {
      await api.promoteProposal(id);
      await Promise.all([get().fetchStatus(), get().fetchProposals()]);
    } finally {
      set({ actionLoading: false });
    }
  },

  rollback: async (id) => {
    set({ actionLoading: true });
    try {
      await api.rollbackProposal(id);
      await Promise.all([get().fetchStatus(), get().fetchProposals()]);
    } finally {
      set({ actionLoading: false });
    }
  },

  optimizeFromSignals: async (pair) => {
    set({ signalOptLoading: true, error: null });
    try {
      const previousTopProposalId = get().proposals[0]?.id ?? null;
      await api.optimizeFromSignals({ pair });
      await Promise.all([get().fetchStatus(), get().fetchProposals()]);
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const latestTopProposalId = get().proposals[0]?.id ?? null;
        if (latestTopProposalId !== previousTopProposalId) {
          break;
        }
        await wait(1500);
        await get().fetchProposals();
      }
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ signalOptLoading: false });
    }
  },
}));
