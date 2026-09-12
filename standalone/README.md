# Standalone Browser App

`cycle-discovery.html` is a **single, self-contained file** — no server, no build step,
no install, no dependencies. Open it in any modern browser and it works.

## How to use

1. Double-click `cycle-discovery.html` (or drag it into a browser tab).
2. Pick a data source:
   - **Demo (synthetic cycles)** — generates a price series with known 21 / 63 / 252-bar
     cycles so you can see the detector recover them. Best first run.
   - **Fetch symbol (Stooq)** — pulls daily data for a ticker (e.g. `AAPL.US`, `^SPX`,
     `BTCUSD`). Note: some browsers block this with CORS; if it fails, use a CSV.
   - **Upload CSV** — drop any OHLCV CSV. It only needs a `date` column and a `close` column.
3. Click **Discover Cycles**.

## What it computes (all in vanilla JS)

| Capability | Status |
|------------|--------|
| Preprocessing (log-returns, detrend, z-score) | ✅ |
| FFT periodogram | ✅ |
| Autocorrelation | ✅ |
| Lomb-Scargle | ✅ |
| Hilbert instantaneous frequency | ✅ |
| Hurst exponent (R/S) | ✅ |
| Consensus across methods | ✅ |
| Power-spectrum chart + cycle table | ✅ |
| Next turning-point projection | ✅ |

## What it does NOT include

These require the Python backend (`PyTorch`, `statsmodels`, `stumpy`, `hmmlearn`, `ephem`),
which can't run in a browser:

- AI models (autoencoder / transformer / LSTM / TCN)
- HMM regime detection
- Matrix-profile motif discovery
- Planetary ephemeris correlations
- Walk-forward / out-of-sample stability testing
- Persistent storage (Postgres / S3), accounts, jobs queue

For those, run the full Docker stack — see the project root `README.md`.

## Hacking on it

Everything lives between the `<script>` tags. The DSP engine is split into clear sections:
FFT → preprocessing → per-method detectors → scoring/consensus → data sources →
analysis orchestration → rendering → UI wiring. To add a method, write a
`methodX(x, minP, maxP)` returning `{ cands: [...] }` and register it in `runAnalysis`.
