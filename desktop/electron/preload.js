/**
 * Preload bridge — exposes a minimal, safe API to the renderer.
 * The UI calls window.hcd.engineUrl() to discover the local backend port
 * instead of a hardcoded NEXT_PUBLIC_API_URL.
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hcd", {
  engineUrl: () => ipcRenderer.invoke("get-engine-url"),
  dataDir: () => ipcRenderer.invoke("get-data-dir"),
  isDesktop: true,
});
