"use client";
import { Clock, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";

export function AnalogPanel() {
  const { results } = useResearchStore();
  const analogData = results?.modules?.analog;
  if (!analogData) return null;

  const { top_analogs = [], composite_projection = {}, projection_confidence = 0 } = analogData;

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-chart-3" />
        <h3 className="text-sm font-semibold">Historical Analogs</h3>
      </div>

      {/* Composite projection */}
      {composite_projection["5d"] !== undefined && (
        <div className="p-2.5 rounded bg-secondary/50 mb-3">
          <p className="text-[10px] text-muted-foreground mb-1.5">
            Weighted Projection (confidence: {(projection_confidence * 100).toFixed(0)}%)
          </p>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(composite_projection).slice(0, 4).map(([horizon, ret]: [string, any]) => (
              <div key={horizon} className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{horizon}</span>
                <span className={`text-xs font-mono font-bold flex items-center gap-1 ${ret > 0 ? "text-primary" : ret < 0 ? "text-destructive" : "text-muted-foreground"}`}>
                  {ret > 0 ? <TrendingUp className="w-3 h-3" /> : ret < 0 ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                  {(ret * 100).toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top analogs list */}
      <div className="space-y-2">
        {top_analogs.slice(0, 5).map((a: any, i: number) => (
          <div key={i} className="flex items-start justify-between text-xs p-2 rounded hover:bg-secondary/30 transition-colors">
            <div>
              <span className="font-mono text-muted-foreground">
                {a.start_date?.slice(0, 10)} → {a.end_date?.slice(0, 10)}
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-primary">Sim: {(a.similarity_score * 100).toFixed(0)}%</span>
                <span className={a.historical_outcome_direction === "up" ? "text-primary" : a.historical_outcome_direction === "down" ? "text-destructive" : "text-muted-foreground"}>
                  {a.historical_outcome_direction}
                </span>
              </div>
            </div>
            <div className="text-right">
              <div className={`font-mono font-bold ${(a.forward_returns?.["5d"] ?? 0) > 0 ? "text-primary" : "text-destructive"}`}>
                {((a.forward_returns?.["5d"] ?? 0) * 100).toFixed(2)}%
              </div>
              <div className="text-muted-foreground text-[10px]">5d fwd</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
