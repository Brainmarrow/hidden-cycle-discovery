/**
 * HIDDEN CYCLE DISCOVERY — Desktop (Electron main process)
 * ==========================================================
 * Architecture:
 *   Electron shell  →  loads the Next.js UI (static export)
 *   Python sidecar  →  the FastAPI backend frozen with PyInstaller,
 *                      spawned as a child process on a local port.
 *   SQLite + local disk replace Postgres + S3 (see desktop_config.py).
 *
 * Lifecycle:
 *   1. Pick a free port.
 *   2. Spawn the bundled `hcd-engine` executable with DESKTOP_MODE=1.
 *   3. Poll /health until the engine is ready.
 *   4. Open the BrowserWindow pointed at the local UI.
 *   5. On quit, kill the sidecar cleanly (SIGTERM, then SIGKILL).
 */
const { app, BrowserWindow, dialog, shell, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const net = require("net");
const http = require("http");

let mainWindow = null;
let engineProcess = null;
let enginePort = 8741;

const isDev = !app.isPackaged;

// ── Resolve bundled resource paths ───────────────────────────────────────────
function resourcePath(...parts) {
  return isDev
    ? path.join(__dirname, "..", "resources", ...parts)
    : path.join(process.resourcesPath, ...parts);
}

function engineBinaryPath() {
  const bin = process.platform === "win32" ? "hcd-engine.exe" : "hcd-engine";
  return resourcePath("engine", bin);
}

function userDataDir() {
  const dir = path.join(app.getPath("userData"), "hcd-data");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// ── Find a free port ─────────────────────────────────────────────────────────
function findFreePort(start = 8741) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(start, () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on("error", () => resolve(findFreePort(start + 1)));
  });
}

// ── Spawn the Python engine sidecar ──────────────────────────────────────────
async function startEngine() {
  enginePort = await findFreePort(8741);
  const binPath = engineBinaryPath();

  if (!fs.existsSync(binPath)) {
    dialog.showErrorBox(
      "Engine missing",
      `The analysis engine was not found at:\n${binPath}\n\n` +
      `Run "npm run build:engine" before packaging.`
    );
    app.quit();
    return;
  }

  engineProcess = spawn(binPath, [], {
    env: {
      ...process.env,
      DESKTOP_MODE: "1",
      HCD_PORT: String(enginePort),
      HCD_DATA_DIR: userDataDir(),
      DEVICE: "cpu",                 // desktop default; GPU users can override
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  engineProcess.stdout.on("data", (d) => console.log(`[engine] ${d}`.trim()));
  engineProcess.stderr.on("data", (d) => console.error(`[engine] ${d}`.trim()));
  engineProcess.on("exit", (code) => {
    console.log(`[engine] exited with code ${code}`);
    engineProcess = null;
  });

  // Wait for /health to respond (max 60s — first launch unpacks PyInstaller)
  const ready = await waitForHealth(`http://127.0.0.1:${enginePort}/health`, 60000);
  if (!ready) {
    dialog.showErrorBox("Engine failed to start",
      "The analysis engine did not become ready within 60 seconds.\n" +
      "Check the logs in the app's user-data folder.");
    app.quit();
  }
}

function waitForHealth(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const tick = () => {
      http.get(url, (res) => {
        if (res.statusCode === 200) return resolve(true);
        retry();
      }).on("error", retry);
    };
    const retry = () => {
      if (Date.now() > deadline) return resolve(false);
      setTimeout(tick, 500);
    };
    tick();
  });
}

// ── Stop the sidecar cleanly ─────────────────────────────────────────────────
function stopEngine() {
  if (!engineProcess) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(engineProcess.pid), "/f", "/t"]);
    } else {
      engineProcess.kill("SIGTERM");
      setTimeout(() => { try { engineProcess && engineProcess.kill("SIGKILL"); } catch (_) {} }, 3000);
    }
  } catch (_) {}
  engineProcess = null;
}

// ── Main window ──────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1080,
    minHeight: 680,
    backgroundColor: "#0b0e14",
    title: "Hidden Cycle Discovery",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  // The UI: a static export of the Next.js frontend, served from disk.
  const uiIndex = resourcePath("ui", "index.html");
  if (fs.existsSync(uiIndex)) {
    mainWindow.loadFile(uiIndex);
  } else if (isDev) {
    // Dev: run `npm run dev` in frontend/ and point here
    mainWindow.loadURL("http://localhost:3000");
  } else {
    dialog.showErrorBox("UI missing", `UI bundle not found at ${uiIndex}`);
  }

  mainWindow.once("ready-to-show", () => mainWindow.show());

  // External links open in the system browser, not in-app
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}

// ── IPC: let the renderer ask where the engine lives ────────────────────────
ipcMain.handle("get-engine-url", () => `http://127.0.0.1:${enginePort}`);
ipcMain.handle("get-data-dir", () => userDataDir());

// ── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  await startEngine();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopEngine();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopEngine);
process.on("exit", stopEngine);
