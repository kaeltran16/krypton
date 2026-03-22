import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { OptimizerStatus, Proposal } from "./types";

interface OptimizerStore {
  status: OptimizerStatus | null;
  proposals: Proposal[];
  loading: boolean;
  actionLoading: boolean;
  error: string | null;

  fetchStatus: () => Promise<void>;
  fetchProposals: () => Promise<void>;
  approve: (id: number) => Promise<void>;
  reject: (id: number, reason?: string) => Promise<void>;
  promote: (id: number) => Promise<void>;
  rollback: (id: number) => Promise<void>;
}

export const useOptimizerStore = create<OptimizerStore>((set, get) => ({
  status: null,
  proposals: [],
  loading: false,
  actionLoading: false,
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
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  reject: async (id, reason) => {
    set({ actionLoading: true });
    try {
      await api.rejectProposal(id, reason);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  promote: async (id) => {
    set({ actionLoading: true });
    try {
      await api.promoteProposal(id);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  rollback: async (id) => {
    set({ actionLoading: true });
    try {
      await api.rollbackProposal(id);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },
}));
