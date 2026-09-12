import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

interface JobStatus {
  status: string;
  progress: number;
  progress_message?: string;
}

interface ResearchState {
  marketDataId: string | null;
  activeJob: string | null;
  jobStatus: JobStatus | null;
  results: any | null;
  isLoading: boolean;

  setMarketDataId: (id: string | null) => void;
  setActiveJob: (id: string | null) => void;
  setJobStatus: (status: JobStatus | null) => void;
  setResults: (results: any) => void;
  setLoading: (loading: boolean) => void;
  reset: () => void;
}

export const useResearchStore = create<ResearchState>()(
  immer((set) => ({
    marketDataId: null,
    activeJob: null,
    jobStatus: null,
    results: null,
    isLoading: false,

    setMarketDataId: (id) => set((s) => { s.marketDataId = id; }),
    setActiveJob: (id) => set((s) => { s.activeJob = id; }),
    setJobStatus: (status) => set((s) => { s.jobStatus = status; }),
    setResults: (results) => set((s) => { s.results = results; }),
    setLoading: (loading) => set((s) => { s.isLoading = loading; }),
    reset: () => set((s) => {
      s.marketDataId = null;
      s.activeJob = null;
      s.jobStatus = null;
      s.results = null;
      s.isLoading = false;
    }),
  }))
);
