# Desktop Apps

Two ways to ship Hidden Cycle Discovery as installable desktop software.

| | **Lite** (Tauri) | **Full** (Electron + Python engine) |
|---|---|---|
| What runs | Browser-feasible cycle detection (FFT, Lomb-Scargle, ACF, Hilbert, Hurst, consensus) | All 10 modules: AI models, HMM, motifs, planetary, stability, broker connections |
| Installer size | ~5 MB | ~300–500 MB |
| Dependencies on user's machine | None | None (Python is frozen inside) |
| Storage | In-memory / CSV | SQLite + local disk (auto-configured) |
| Build difficulty | Easy (Rust toolchain) | Moderate (Node + Python + PyInstaller) |

---

## Lite — `desktop/tauri-lite/`

Wraps `standalone/cycle-discovery.html` in a native window. The HTML file is
copied to `ui/index.html` and Tauri serves it locally.

### Build

```bash
# Prereqs: Rust (rustup.rs) + Tauri CLI
cargo install tauri-cli --version "^2"

cd desktop/tauri-lite/src-tauri
cargo tauri build
# Installers land in target/release/bundle/
#   Windows: .msi    macOS: .dmg    Linux: .AppImage / .deb
```

Add real icons to `src-tauri/icons/` before release builds
(`cargo tauri icon path/to/1024.png` generates the whole set).

---

## Full — `desktop/electron/`

Architecture (same pattern as Postman / Jupyter Desktop):

```
┌────────────────────────────────────────────┐
│ Electron shell (main.js)                   │
│   1. finds a free local port               │
│   2. spawns the frozen Python engine       │──► hcd-engine(.exe)
│   3. waits for /health                     │     FastAPI + all ML modules
│   4. loads the Next.js UI from disk        │     SQLite + local storage
│   5. kills the engine cleanly on quit      │     (DESKTOP_MODE=1)
└────────────────────────────────────────────┘
```

What changes in desktop mode (`backend/desktop_main.py`, all validated):
- **Postgres → SQLite** — models use dialect-agnostic UUID/JSONB types, all 12
  tables create cleanly on SQLite (tested, including insert/select round-trips)
- **S3 → local disk** — `StorageService` is monkeypatched to file operations
- **Celery → eager mode** — analyses run in-process; no Redis/broker needed
- **Bind 127.0.0.1 only** — engine is never exposed to the network

### Build

```bash
# Prereqs: Node 18+, Python 3.11 with backend deps installed

# 1. Freeze the Python engine
cd backend
pip install -r requirements-desktop.txt
pyinstaller --clean hcd-engine.spec        # → dist/hcd-engine/

# 2. Static-export the frontend
cd ../frontend
# (set output: 'export' in next.config and use relative API base via window.hcd)
npm run build                               # → out/

# 3. Package
cd ../desktop/electron
npm install
npm run dist                                # runs copy scripts + electron-builder
# Installers land in desktop/electron/dist/
#   Windows: NSIS .exe   macOS: .dmg   Linux: .AppImage / .deb
```

### Frontend note

In desktop mode the UI should discover the engine port via the preload bridge
instead of a hardcoded URL:

```ts
const base = window.hcd ? await window.hcd.engineUrl() : process.env.NEXT_PUBLIC_API_URL;
```

### GPU

The desktop build defaults to `DEVICE=cpu` so it runs everywhere. Users with
NVIDIA GPUs can set `DEVICE=cuda` in the app's environment; the frozen engine
includes torch, so CUDA works if the system has drivers.

### Data location

All user data lives in the OS-standard app-data dir
(`%APPDATA%/Hidden Cycle Discovery/hcd-data` on Windows,
`~/Library/Application Support/...` on macOS, `~/.config/...` on Linux):
`hcd.db` (SQLite), `storage/` (datasets), `artifacts/` (trained models).
Deleting that folder fully resets the app.
