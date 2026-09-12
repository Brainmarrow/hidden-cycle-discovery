"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataInputPanel } from "@/components/research/DataInputPanel";
import { JobProgressPanel } from "@/components/research/JobProgressPanel";
import { CycleResultsPanel } from "@/components/cycle/CycleResultsPanel";
import { PatternResultsPanel } from "@/components/cycle/PatternResultsPanel";
import { AnalogPanel } from "@/components/cycle/AnalogPanel";
import { ResearchSummaryPanel } from "@/components/research/ResearchSummaryPanel";
import { useResearchStore } from "@/store/researchStore";

export default function DashboardPage() {
  const { activeJob, results, marketDataId } = useResearchStore();

  return (
    <AppShell>
      <div className="grid grid-cols-12 gap-4 h-full min-h-screen p-4">

        {/* ── Left panel: inputs + job control ─────────────────────── */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-4">
          <DataInputPanel />
          {activeJob && <JobProgressPanel />}
        </div>

        {/* ── Center: main analysis results ─────────────────────────── */}
        <div className="col-span-12 lg:col-span-6 flex flex-col gap-4">
          {results ? (
            <>
              <ResearchSummaryPanel />
              <CycleResultsPanel />
            </>
          ) : (
            <EmptyState />
          )}
        </div>

        {/* ── Right panel: patterns + analogs ───────────────────────── */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-4">
          {results && (
            <>
              <PatternResultsPanel />
              <AnalogPanel />
            </>
          )}
        </div>

      </div>
    </AppShell>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-96 text-center gap-6">
      <div className="relative">
        <div className="w-24 h-24 rounded-full border-2 border-primary/30 flex items-center justify-center">
          <div className="w-16 h-16 rounded-full border-2 border-primary/50 flex items-center justify-center">
            <div className="w-8 h-8 rounded-full bg-primary/20 animate-pulse" />
          </div>
        </div>
        <div className="absolute inset-0 rounded-full animate-ping border border-primary/10" />
      </div>

      <div>
        <h2 className="text-xl font-semibold text-gradient mb-2">
          Hidden Cycle Discovery AI
        </h2>
        <p className="text-muted-foreground text-sm max-w-sm">
          Select a market instrument, choose your timeframe, and run the analysis
          to discover hidden cycles, repeating patterns, and temporal dependencies.
        </p>
      </div>

      <div className="terminal-block text-left w-full max-w-sm">
        <div className="text-muted-foreground mb-1">// Supported methods</div>
        <div className="text-primary">FFT · Lomb-Scargle · Wavelets</div>
        <div className="text-primary">Autocorrelation · Hilbert · Hurst</div>
        <div className="text-accent">DTW · KMeans · HMM Regimes</div>
        <div className="text-chart-3">Planetary Correlations (Pro)</div>
        <div className="text-chart-4">Analog Engine · AI Models (Pro)</div>
      </div>
    </div>
  );
}
