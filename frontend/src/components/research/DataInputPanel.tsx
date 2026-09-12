"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Play, Upload, ChevronDown, AlertCircle } from "lucide-react";
import { useResearchStore } from "@/store/researchStore";
import { api } from "@/lib/api";
import toast from "react-hot-toast";

const INSTRUMENTS = [
  { group: "Indian Indices", items: ["NIFTY", "BANKNIFTY", "SENSEX", "NIFTY IT", "NIFTY BANK"] },
  { group: "US Indices",     items: ["S&P500 (SPY)", "NASDAQ (QQQ)", "DOW (DIA)", "VIX"] },
  { group: "Crypto",         items: ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"] },
  { group: "Forex",          items: ["EUR/USD", "USD/JPY", "GBP/USD", "USD/INR"] },
  { group: "Commodities",    items: ["GOLD (GLD)", "SILVER (SLV)", "OIL (USO)", "NATURAL GAS"] },
];

const INTERVALS = [
  { value: "1d",  label: "Daily",       free: true },
  { value: "1h",  label: "Hourly",      free: true },
  { value: "15m", label: "15 Minutes",  free: false },
  { value: "5m",  label: "5 Minutes",   free: false },
  { value: "1m",  label: "1 Minute",    free: false },
];

const DATE_PRESETS = [
  { label: "1Y",  value: "1y"  },
  { label: "3Y",  value: "3y"  },
  { label: "5Y",  value: "5y"  },
  { label: "10Y", value: "10y" },
  { label: "20Y", value: "20y" },
  { label: "MAX", value: "max" },
];

export function DataInputPanel() {
  const { setMarketDataId, setActiveJob, setLoading } = useResearchStore();

  const [symbol, setSymbol] = useState("NIFTY");
  const [customSymbol, setCustomSymbol] = useState("");
  const [interval, setInterval] = useState("1d");
  const [datePreset, setDatePreset] = useState("10y");
  const [showDropzone, setShowDropzone] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // CSV upload dropzone
  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("symbol", file.name.replace(".csv", "").toUpperCase());
    formData.append("interval", interval);

    try {
      setIsLoading(true);
      const res = await api.post("/market-data/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setMarketDataId(res.data.market_data_id);
      toast.success(`Loaded ${res.data.n_bars} bars from ${file.name}`);
      setShowDropzone(false);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Upload failed");
    } finally {
      setIsLoading(false);
    }
  }, [interval]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"] },
    multiple: false,
  });

  const handleFetch = async () => {
    const sym = customSymbol || symbol;
    if (!sym) return;

    try {
      setIsLoading(true);
      setLoading(true);

      // Fetch data
      const fetchRes = await api.post("/market-data/fetch", {
        symbol: sym,
        interval,
        source: _detectSource(sym),
        start_date: _datePresetToStart(datePreset),
      });

      const marketDataId = fetchRes.data.market_data_id;
      setMarketDataId(marketDataId);

      // Poll until ready
      await pollDataReady(marketDataId);

      // Trigger analysis
      const analysisRes = await api.post("/research/analyze", {
        market_data_id: marketDataId,
        lookback_bars: 60,
      });

      setActiveJob(analysisRes.data.job_id);
      toast.success("Analysis started");

    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Failed to start analysis");
    } finally {
      setIsLoading(false);
      setLoading(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
        <h2 className="text-sm font-semibold">Data Input</h2>
      </div>

      {/* Symbol selector */}
      <div>
        <label className="text-xs text-muted-foreground mb-1.5 block">Instrument</label>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="w-full bg-input border border-border rounded px-3 py-2 text-sm text-foreground"
        >
          {INSTRUMENTS.map((group) => (
            <optgroup key={group.group} label={group.group}>
              {group.items.map((item) => (
                <option key={item} value={item.split(" ")[0]}>
                  {item}
                </option>
              ))}
            </optgroup>
          ))}
          <optgroup label="Custom">
            <option value="_custom">Custom Symbol...</option>
          </optgroup>
        </select>
      </div>

      {/* Custom symbol input */}
      {(symbol === "_custom") && (
        <input
          type="text"
          placeholder="e.g. RELIANCE.NS, AAPL, BTC/USDT"
          value={customSymbol}
          onChange={(e) => setCustomSymbol(e.target.value.toUpperCase())}
          className="w-full bg-input border border-border rounded px-3 py-2 text-sm"
        />
      )}

      {/* Interval */}
      <div>
        <label className="text-xs text-muted-foreground mb-1.5 block">Interval</label>
        <div className="grid grid-cols-5 gap-1">
          {INTERVALS.map((iv) => (
            <button
              key={iv.value}
              onClick={() => setInterval(iv.value)}
              disabled={!iv.free}
              title={!iv.free ? "Requires Pro" : undefined}
              className={`py-1.5 rounded text-xs font-medium transition-colors relative
                ${interval === iv.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
                }
                ${!iv.free ? "opacity-40 cursor-not-allowed" : ""}
              `}
            >
              {iv.label}
              {!iv.free && (
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-primary rounded-full" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Date range */}
      <div>
        <label className="text-xs text-muted-foreground mb-1.5 block">History</label>
        <div className="grid grid-cols-6 gap-1">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => setDatePreset(p.value)}
              className={`py-1.5 rounded text-xs font-medium transition-colors
                ${datePreset === p.value
                  ? "bg-primary/20 text-primary border border-primary/50"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
                }
              `}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* CSV Upload toggle */}
      <button
        onClick={() => setShowDropzone(!showDropzone)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Upload className="w-3 h-3" />
        Upload CSV instead
        <ChevronDown className={`w-3 h-3 transition-transform ${showDropzone ? "rotate-180" : ""}`} />
      </button>

      {showDropzone && (
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors
            ${isDragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}
          `}
        >
          <input {...getInputProps()} />
          <Upload className="w-6 h-6 mx-auto mb-2 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">
            {isDragActive ? "Drop CSV here..." : "Drop OHLCV CSV or click to browse"}
          </p>
          <p className="text-[10px] text-muted-foreground/60 mt-1">
            Required columns: date, open, high, low, close
          </p>
        </div>
      )}

      {/* Run button */}
      <button
        onClick={handleFetch}
        disabled={isLoading}
        className="flex items-center justify-center gap-2 w-full py-2.5 rounded bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50"
      >
        {isLoading ? (
          <>
            <div className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <Play className="w-4 h-4" />
            Discover Cycles
          </>
        )}
      </button>
    </div>
  );
}

// Helpers
function _detectSource(symbol: string): string {
  if (symbol.includes("/") || ["BTC", "ETH", "SOL", "BNB"].some(c => symbol.includes(c))) return "ccxt";
  if (symbol.endsWith(".NS") || symbol.endsWith(".BO")) return "yfinance";
  if (["NIFTY", "BANKNIFTY", "SENSEX"].includes(symbol)) return "nsepy";
  return "yfinance";
}

function _datePresetToStart(preset: string): string {
  const now = new Date();
  const years = preset === "max" ? 25 : parseInt(preset);
  now.setFullYear(now.getFullYear() - years);
  return now.toISOString().split("T")[0];
}

async function pollDataReady(marketDataId: string, maxAttempts = 30): Promise<void> {
  for (let i = 0; i < maxAttempts; i++) {
    const res = await api.get(`/market-data/${marketDataId}`);
    if (res.data.fetch_status === "ready") return;
    if (res.data.fetch_status === "failed") throw new Error("Data fetch failed");
    await new Promise(r => setTimeout(r, 2000));
  }
  throw new Error("Data fetch timeout");
}
