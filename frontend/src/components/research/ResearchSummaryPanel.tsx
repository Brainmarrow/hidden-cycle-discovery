"use client";
import { Lightbulb, Shield, AlertTriangle } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";

export function ResearchSummaryPanel() {
  const { results } = useResearchStore();
  const report = results?.report;
  if (!report) return null;

  return (
    <div className="glow-card">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="w-4 h-4 text-primary" />
        <h2 className="text-sm font-semibold">Key Findings</h2>
        <span className="text-[10px] text-muted-foreground ml-auto">{report.generated_at?.slice(0, 10)}</span>
      </div>
      <div className="space-y-2">
        {(report.key_findings ?? []).slice(0, 6).map((finding: string, i: number) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <div className="w-1.5 h-1.5 rounded-full bg-primary mt-1 flex-shrink-0" />
            <span className="text-foreground">{finding}</span>
          </div>
        ))}
      </div>

      {/* Stability summary */}
      {results?.modules?.stability && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="flex items-center gap-2 text-xs">
            {(results.modules.stability.stable_cycles?.length ?? 0) > 0 ? (
              <><Shield className="w-3.5 h-3.5 text-primary" />
              <span className="text-primary">{results.modules.stability.stable_cycles.length} stable cycles confirmed</span></>
            ) : (
              <><AlertTriangle className="w-3.5 h-3.5 text-destructive" />
              <span className="text-muted-foreground">No high-stability cycles found</span></>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
