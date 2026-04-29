"use strict";
/**
 * Electron preload script — runs in the renderer before page scripts.
 *
 * contextIsolation is enabled so Node.js APIs are NOT exposed to the web
 * page.  We expose only a minimal, safe surface via contextBridge.
 */

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("desktopApp", {
  /** True when the page is running inside the Electron desktop app. */
  isDesktop: true,
  /** Electron / Node.js platform string: 'win32', 'darwin', 'linux'. */
  platform: process.platform,
});
