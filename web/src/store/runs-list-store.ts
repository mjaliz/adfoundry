import { create } from "zustand";

import { listRuns } from "@/lib/api";
import type { RunSummary } from "@/types/api";

interface RunsListState {
  runs: RunSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export const useRunsListStore = create<RunsListState>((set) => ({
  runs: [],
  loading: false,
  error: null,
  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const runs = await listRuns();
      set({ runs, loading: false });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "Failed to load runs",
      });
    }
  },
}));
