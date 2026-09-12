# Running & Building on a Low-RAM Windows PC (≤4GB)

This guide replaces Docker/PyTorch-heavy steps with paths that actually work on
a constrained machine. Three pieces:

1. **Full backend, running locally** — no Docker, no Postgres, no Redis server,
   no PyTorch. ~500MB install instead of ~5GB. This is "Step 2" made light.
2. **Lite desktop app (Tauri)** — built in the cloud, installs on your PC as a
   normal ~5MB app. This is "Step 3."
3. **Full desktop app (Electron + all 10 modules)** — also built in the cloud
   (freezing PyTorch needs more RAM than 4GB comfortably gives you), you just
   download the finished installer. This is "Step 4."

---

## 1. Full backend locally — no Docker (replaces Step 2)

### What's different from the Docker version

| Full stack (Docker) | Lite (this guide) |
|---|---|
| Postgres | SQLite (`aiosqlite`) — no server |
| Redis | `fakeredis` — in-process, no server |
| Celery worker + broker | Eager mode — tasks run inline |
| S3 | Local disk |
| PyTorch (AI Models) | Skipped — everything else works |
| ~5GB download | ~500MB download |

Every module except **AI Models** (autoencoder/transformer/LSTM/TCN, which
needs PyTorch) works exactly the same: cycle detection, pattern discovery,
planetary correlations, features, analogs, stability, and all 10 data
providers (5 Indian brokers + 5 global sources).

### Setup (one time)

1. Install **Python 3.11** from [python.org](https://www.python.org/downloads/)
   — during install, check **"Add python.exe to PATH"**.
2. Unzip the project, open a terminal in `backend/`.
3. Double-click `run-lite-windows.bat` (or run it from a terminal).

That's it — the script creates a virtual environment, installs the lite
dependencies (~500MB, one time), and starts the server. Every time after
that, running the same `.bat` file just starts the server in a few seconds.

### Using it

Once it says `Starting engine on http://127.0.0.1:8741`, open:

- **http://127.0.0.1:8741/docs** — interactive API (Swagger UI). This is the
  lightest way to use every module — no separate frontend to run.
- Register a user, log in, then use **market-data → fetch** with a symbol
  like `NIFTY` or `AAPL`, then **research → analyze** to run cycle detection.

If you also want the polished web UI (not required — `/docs` covers
everything), you can run the Next.js frontend separately, but on 4GB RAM
prefer **production build** over dev mode (dev mode's hot-reload watcher
uses continuous extra RAM):

```bash
cd frontend
npm install
npm run build
npm start
# → http://localhost:3000, pointed at http://127.0.0.1:8741
```

Close other heavy apps (browser with many tabs, etc.) while `npm install`
runs — that step is the most RAM-hungry part of this whole path.

### Stopping / resetting

- Stop: close the terminal window, or Ctrl+C.
- Reset all data: delete `%USERPROFILE%\.hidden-cycle-discovery`.

---

## 2 & 3. Desktop apps — built in the cloud, not on your PC

Building the Lite (Tauri) app needs a Rust compiler. Building the Full
(Electron) app needs PyInstaller to freeze PyTorch + SciPy into an
executable — that step alone comfortably wants more than 4GB while it runs.
Rather than fight your PC's limits, both builds are already set up to run on
**GitHub's free cloud servers** (7GB RAM machines, no cost to you) via
`.github/workflows/build-desktop.yml`. You push code; GitHub compiles;
you download the finished installer.

### One-time setup

1. Create a free account at [github.com](https://github.com) if you don't
   have one.
2. Create a new **empty** repository (any name, e.g. `hidden-cycle-discovery`).
   Keep it private if you prefer — Actions works the same either way.
3. Install [Git for Windows](https://git-scm.com/download/win) if you don't
   have it.
4. In a terminal, inside the unzipped project folder:

   ```bash
   git init
   git add .
   git commit -m "initial"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

### Trigger the build

1. On GitHub, open your repo → **Actions** tab.
2. Click **Build Desktop Installers** in the left sidebar.
3. Click **Run workflow** → **Run workflow** (green button).
4. Wait — Lite finishes in a few minutes; Full (freezing PyTorch) takes
   roughly 15–25 minutes. You can close the browser tab; check back later.

### Download your installer

1. Click into the finished run (green checkmark).
2. Scroll to **Artifacts** at the bottom.
3. Download:
   - `cycle-discovery-lite-windows-latest` → unzip → run the `.msi`
   - `hidden-cycle-discovery-full-windows-latest` → unzip → run the `.exe`
4. Install like any normal Windows app. Your PC only ever runs the finished,
   already-compiled installer — never the build itself.

### Re-building after you change something

Same three commands, any time you edit the code:

```bash
git add .
git commit -m "update"
git push
```

Then repeat "Trigger the build" above. (Or add `on: push: branches: [main]`
to the workflow file if you want it to build automatically on every push —
left as manual-only by default so it doesn't burn your Actions minutes on
every small commit.)

### If you'd rather not use GitHub

The standalone HTML (`standalone/cycle-discovery.html`) needs no build at
all — double-click it and it works, with the same cycle-detection math the
Lite app ships. Use that if you want zero setup and don't need the extra
modules or Indian broker connections.
