"use strict";
/**
 * CRA Tax Helper — Electron main process.
 *
 * Responsibilities:
 *   1. Spawn the bundled Python/FastAPI server (or the dev Python process).
 *   2. Wait for the server to respond on the health endpoint.
 *   3. Open a BrowserWindow pointing at http://127.0.0.1:<PORT>.
 *   4. Kill the server process cleanly when the window is closed.
 *
 * Code paths:
 *   Production (packaged): spawns dist-server/cra-taxhelper-server(.exe)
 *                          bundled into resources/server/ by electron-builder.
 *   Development:           spawns `python desktop.py` from the repo root.
 */

const { app, BrowserWindow, shell, Menu } = require("electron");
const { spawn } = require("child_process");
const path  = require("path");
const http  = require("http");

const PORT = parseInt(process.env.PORT || "8765", 10);
const DEV  = !app.isPackaged;

let serverProcess = null;
let mainWindow    = null;

// ── Resolve the server executable ────────────────────────────────────────────

function spawnServer() {
  let child;

  if (app.isPackaged) {
    // Production: bundled executable placed by electron-builder extraResources
    const exeName =
      process.platform === "win32"
        ? "cra-taxhelper-server.exe"
        : "cra-taxhelper-server";
    const exePath = path.join(process.resourcesPath, "server", exeName);

    child = spawn(exePath, [], {
      env: { ...process.env, PORT: String(PORT) },
      stdio: ["ignore", "pipe", "pipe"],
    });
  } else {
    // Development: run desktop.py with the system Python interpreter
    const python =
      process.platform === "win32" ? "python" : "python3";
    const desktopPy = path.join(__dirname, "..", "desktop.py");

    child = spawn(python, [desktopPy], {
      env: { ...process.env, PORT: String(PORT) },
      cwd: path.join(__dirname, ".."),
      stdio: ["ignore", "pipe", "pipe"],
    });
  }

  child.stdout.on("data", (d) => {
    if (DEV) process.stdout.write(`[server] ${d}`);
  });
  child.stderr.on("data", (d) => {
    if (DEV) process.stderr.write(`[server] ${d}`);
  });
  child.on("exit", (code) => {
    if (DEV) console.log(`[server] exited with code ${code}`);
  });

  return child;
}

// ── Wait for server to be ready ───────────────────────────────────────────────

function waitForServer(maxRetries = 60) {
  return new Promise((resolve, reject) => {
    let attempts = 0;

    function attempt() {
      const req = http.get(
        `http://127.0.0.1:${PORT}/health`,
        (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else {
            retry();
          }
        }
      );
      req.on("error", retry);
      req.setTimeout(500, () => { req.destroy(); retry(); });
    }

    function retry() {
      attempts++;
      if (attempts >= maxRetries) {
        reject(new Error(`Server did not start after ${maxRetries} attempts`));
      } else {
        setTimeout(attempt, 500);
      }
    }

    attempt();
  });
}

// ── Create the main window ────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1400,
    height: 900,
    minWidth:  900,
    minHeight: 600,
    title:  "CRA Tax Helper",
    webPreferences: {
      preload:          path.join(__dirname, "preload.js"),
      nodeIntegration:  false,
      contextIsolation: true,
      // Allow the app's own localhost server only
      webSecurity: true,
    },
    // Use platform icon if supplied in build/
    ...(process.platform !== "darwin" && {
      icon: path.join(__dirname, "build", "icon.png"),
    }),
  });

  mainWindow.loadURL(`http://127.0.0.1:${PORT}`);

  // Open <a target="_blank"> links in the system browser, not a new Electron window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Remove default menu bar (the app has its own nav)
  Menu.setApplicationMenu(null);

  if (DEV) mainWindow.webContents.openDevTools({ mode: "detach" });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  serverProcess = spawnServer();

  try {
    await waitForServer(60);
  } catch (err) {
    console.error("Fatal: Python server failed to start.", err.message);
    if (serverProcess) { serverProcess.kill(); serverProcess = null; }
    app.quit();
    return;
  }

  createWindow();

  app.on("activate", () => {
    // macOS: re-create window when dock icon is clicked and no windows are open
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  killServer();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", killServer);

function killServer() {
  if (serverProcess) {
    serverProcess.kill();
    serverProcess = null;
  }
}
