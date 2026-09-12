"use client";
// PatternResultsPanel.tsx
import { GitBranch, ArrowRight } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";

export function PatternResultsPanel() {
  const { results } = useResearchStore();
  const patterns = results?.modules?.pattern_discovery?.patterns ?? [];
  const regimes = results?.modules?.pattern_discovery?.regime_stats;

  if (!patterns.length && !regimes) return null;

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <GitBranch className="w-4 h-4 text-accent" />
        <h3 className="text-sm font-semibold">Pattern Discovery</h3>
        <span className="text-xs text-muted-foreground">({patterns.length} patterns)</span>
      </div>

      {/* Top patterns */}
      <div className="space-y-2">
        {patterns.slice(0, 5).map((p: any, i: number) => (
          <div key={i} className="p-2.5 rounded bg-secondary/50 text-xs">
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium text-foreground capitalize">
                {p.pattern_type.replace(/_/g, " ")}
              </span>
              <span className={`font-mono ${p.sharpe_like > 0 ? "text-primary" : "text-destructive"}`}>
                Sharpe: {p.sharpe_like.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-3 text-muted-foreground">
              <span>{p.occurrence_count}× occurrences</span>
              <span>~{Math.round(p.avg_duration_bars)}b avg</span>
              <span className={p.hit_rate > 0.5 ? "text-primary" : "text-destructive"}>
                {(p.hit_rate * 100).toFixed(0)}% hit rate
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Market regimes */}
      {regimes && (
        <div className="mt-3 pt-3 border-t border-border">
          <p className="text-xs text-muted-foreground mb-2">Market Regimes (HMM)</p>
          <div className="space-y-1.5">
            {Object.entries(regimes).map(([key, stat]: [string, any]) => (
              <div key={key} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground capitalize">
                  {stat.label?.replace(/_/g, " ") ?? key}
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-muted-foreground">{(stat.pct * 100).toFixed(0)}%</span>
                  <span className={`font-mono ${stat.sharpe > 0 ? "text-primary" : "text-destructive"}`}>
                    SR: {stat.sharpe.toFixed(2)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
