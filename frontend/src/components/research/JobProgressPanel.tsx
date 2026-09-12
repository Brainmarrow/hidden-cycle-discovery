"use client";

import { useEffect, useRef } from "react";
import { CheckCircle, XCircle, Loader2, Clock } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";
import { api } from "@/lib/api";

const MODULE_LABELS: Record<string, string> = {
  preprocessing:      "Preprocessing",
  cycle_detection:    "Cycle Detection (FFT/Wavelets)",
  pattern_discovery:  "Pattern Discovery (DTW)",
  features:           "Feature Discovery (1000+ features)",
  stability:          "Stability Testing (Walk-Forward)",
  analog:             "Analog Engine",
  planetary:          "Planetary Correlations",
  ai_model:           "AI Model Training (GPU)",
};

export function JobProgressPanel() {
  const { activeJob, setResults, setActiveJob } = useResearchStore();
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const jobQuery = useJobStatus(activeJob);

  useEffect(() => {
    if (!activeJob) return;

    intervalRef.current = setInterval(async () => {
      try {
        const res = await api.get(`/research/jobs/${activeJob}`);
        const job = res.data;

        if (job.status === "completed") {
          clearInterval(intervalRef.current!);
          // Fetch full result
          const resultRes = await api.get(`/research/jobs/${activeJob}/result`);
          setResults(resultRes.data.result);
          setActiveJob(null);
        } else if (job.status === "failed") {
          clearInterval(intervalRef.current!);
          setActiveJob(null);
        }
      } catch (e) {
        clearInterval(intervalRef.current!);
      }
    }, 2000);

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [activeJob]);

  if (!activeJob) return null;

  const progress = jobQuery?.progress ?? 0;
  const message = jobQuery?.progress_message ?? "Processing...";
  const status = jobQuery?.status ?? "running";

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Loader2 className="w-4 h-4 text-primary animate-spin" />
        <h3 className="text-sm font-semibold">Analysis Running</h3>
        <span className="ml-auto text-xs text-muted-foreground font-mono">
          {Math.round(progress)}%
        </span>
      </div>

      {/* Progress bar */}
      <div className="job-progress-bar mb-3">
        <div className="job-progress-fill" style={{ width: `${progress}%` }} />
      </div>

      {/* Current step */}
      <p className="text-xs text-primary font-mono truncate">{message}</p>

      {/* Module checklist */}
      <div className="mt-3 space-y-1.5">
        {Object.entries(MODULE_LABELS).map(([key, label]) => {
          const completed = progress > _moduleProgress(key);
          const current = message.toLowerCase().includes(key.replace("_", " ").split(" ")[0]);

          return (
            <div key={key} className="flex items-center gap-2">
              {completed ? (
                <CheckCircle className="w-3 h-3 text-primary flex-shrink-0" />
              ) : current ? (
                <Loader2 className="w-3 h-3 text-accent animate-spin flex-shrink-0" />
              ) : (
                <Clock className="w-3 h-3 text-muted-foreground/40 flex-shrink-0" />
              )}
              <span className={`text-[10px] ${completed ? "text-foreground" : current ? "text-accent" : "text-muted-foreground/40"}`}>
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function _moduleProgress(module: string): number {
  const order = ["preprocessing", "cycle_detection", "pattern_discovery", "features", "stability", "analog", "planetary", "ai_model"];
  const idx = order.indexOf(module);
  return ((idx + 1) / order.length) * 95;
}

function useJobStatus(jobId: string | null) {
  const [status, setStatus] = useResearchStore(s => [s.jobStatus, s.setJobStatus] as const);
  return status;
}
