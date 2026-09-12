"use client";

import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell, ReferenceLine, ScatterChart, Scatter
} from "recharts";
import { Waves, TrendingUp, TrendingDown, Activity } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";

function strengthColor(s: number): string {
  if (s >= 0.7) return "hsl(160, 80%, 50%)";
  if (s >= 0.4) return "hsl(45, 95%, 55%)";
  return "hsl(0, 72%, 51%)";
}

function strengthLabel(s: number): string {
  if (s >= 0.7) return "High";
  if (s >= 0.4) return "Medium";
  return "Low";
}

function formatPeriod(bars: number, cal: number): string {
  if (cal >= 365) return `${(cal / 365).toFixed(1)}Y`;
  if (cal >= 30)  return `${Math.round(cal / 30)}M`;
  if (cal >= 7)   return `${Math.round(cal / 7)}W`;
  return `${Math.round(cal)}D`;
}

export function CycleResultsPanel() {
  const { results } = useResearchStore();
  const [view, setView] = useState<"bar" | "scatter" | "table">("bar");

  const cycles = results?.modules?.cycle_detection?.dominant_cycles ?? [];
  const hurst = results?.modules?.cycle_detection?.hurst_exponent;

  if (!cycles.length) return null;

  const chartData = cycles.slice(0, 15).map((c: any) => ({
    name: formatPeriod(c.period_bars, c.period_calendar),
    period: c.period_bars,
    strength: parseFloat((c.strength * 100).toFixed(1)),
    power: parseFloat((c.power * 100).toFixed(1)),
    method: c.method,
    confidence: c.confidence,
    raw: c,
  }));

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Waves className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">Detected Cycles</h2>
          <span className="text-xs text-muted-foreground">({cycles.length} found)</span>
        </div>

        {/* View toggle */}
        <div className="flex rounded overflow-hidden border border-border">
          {(["bar", "scatter", "table"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-2 py-1 text-xs transition-colors ${
                view === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Hurst indicator */}
      {hurst !== undefined && (
        <div className="flex items-center gap-3 mb-4 p-2 rounded bg-secondary text-xs">
          <Activity className="w-3.5 h-3.5 text-accent" />
          <span className="text-muted-foreground">Hurst Exponent:</span>
          <span className={`font-mono font-bold ${
            hurst > 0.55 ? "text-primary" : hurst < 0.45 ? "text-destructive" : "text-accent"
          }`}>
            {hurst.toFixed(3)}
          </span>
          <span className="text-muted-foreground">
            {hurst > 0.55 ? "Trending (persistent)" : hurst < 0.45 ? "Mean-reverting" : "Random walk"}
          </span>
        </div>
      )}

      {/* Bar chart */}
      {view === "bar" && (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 5, right: 5, bottom: 20, left: 0 }}>
            <XAxis
              dataKey="name"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
              angle={-45}
              textAnchor="end"
              interval={0}
            />
            <YAxis
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "6px",
                fontSize: "11px",
              }}
              formatter={(value: any, name: string) => [`${value}%`, name === "strength" ? "Strength" : "Power"]}
              labelFormatter={(label) => `Period: ${label}`}
            />
            <Bar dataKey="strength" name="Strength" radius={[2, 2, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={index} fill={strengthColor(entry.strength / 100)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      {/* Scatter: period vs strength */}
      {view === "scatter" && (
        <ResponsiveContainer width="100%" height={220}>
          <ScatterChart margin={{ top: 5, right: 5, bottom: 20, left: 20 }}>
            <XAxis
              dataKey="period"
              name="Period (bars)"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
              label={{ value: "Period (bars)", position: "insideBottom", offset: -10, fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
            />
            <YAxis
              dataKey="strength"
              name="Strength %"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
            />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", fontSize: "11px" }}
              formatter={(v: any, n: string) => [n === "strength" ? `${v}%` : v, n === "period" ? "Period" : "Strength"]}
            />
            <Scatter data={chartData} fill="hsl(var(--primary))" />
          </ScatterChart>
        </ResponsiveContainer>
      )}

      {/* Table view */}
      {view === "table" && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left py-2 pr-3">Period</th>
                <th className="text-left py-2 pr-3">Method</th>
                <th className="text-right py-2 pr-3">Strength</th>
                <th className="text-right py-2 pr-3">Confidence</th>
                <th className="text-left py-2">Next Turn</th>
              </tr>
            </thead>
            <tbody>
              {cycles.slice(0, 15).map((c: any, i: number) => (
                <tr key={i} className="border-b border-border/50 hover:bg-secondary/30 transition-colors">
                  <td className="py-2 pr-3 font-mono text-foreground">
                    {formatPeriod(c.period_bars, c.period_calendar)}
                    <span className="text-muted-foreground ml-1">({Math.round(c.period_bars)}b)</span>
                  </td>
                  <td className="py-2 pr-3 text-muted-foreground">{c.method}</td>
                  <td className="py-2 pr-3 text-right">
                    <span style={{ color: strengthColor(c.strength) }} className="font-semibold">
                      {(c.strength * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right text-muted-foreground">
                    {(c.confidence * 100).toFixed(0)}%
                  </td>
                  <td className="py-2">
                    {c.next_turning_point_bars != null ? (
                      <span className={`flex items-center gap-1 ${c.turning_point_type === "peak" ? "text-destructive" : "text-primary"}`}>
                        {c.turning_point_type === "peak" ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                        {c.next_turning_point_bars}b
                      </span>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Consensus cycles */}
      {results?.modules?.cycle_detection?.consensus_cycles?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border">
          <p className="text-xs text-muted-foreground mb-2">
            Consensus cycles (confirmed by multiple methods):
          </p>
          <div className="flex flex-wrap gap-1.5">
            {results.modules.cycle_detection.consensus_cycles.slice(0, 5).map((c: any, i: number) => (
              <span
                key={i}
                className="text-[10px] font-mono px-2 py-0.5 rounded border"
                style={{
                  borderColor: strengthColor(c.strength),
                  color: strengthColor(c.strength),
                  background: `${strengthColor(c.strength)}15`,
                }}
              >
                {formatPeriod(c.period_bars, c.period_calendar)} · {(c.strength * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
