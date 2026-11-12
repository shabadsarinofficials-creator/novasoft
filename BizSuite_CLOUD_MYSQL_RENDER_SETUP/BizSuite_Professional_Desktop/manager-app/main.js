const { app, BrowserWindow, dialog, ipcMain, Menu } = require("electron");
const path = require("path");
const fs = require("fs");
const { autoUpdater } = require("electron-updater");

app.setName("BizSuite Manager");
app.setAppUserModelId("com.bizsuite.manager");
app.setPath("userData", path.join(app.getPath("appData"), "BizSuite Manager"));

function configPath() { return path.join(app.getPath("userData"), "config.json"); }
function readSavedConfig() {
  try {
    const j = JSON.parse(fs.readFileSync(configPath(), "utf8"));
    if (typeof j.apiBase === "string" && /^https?:\/\//i.test(j.apiBase)) return j.apiBase.replace(/\/+$/, "");
  } catch {}
  return "";
}
function readApiBase() {
  return readSavedConfig() || process.env.BIZSUITE_API_URL || "http://127.0.0.1:8000";
}
function normalizeApiBase(value) {
  if (typeof value !== "string" || !value.trim()) throw new Error("Enter the server URL first.");
  let u;
  try { u = new URL(value.trim()); } catch { throw new Error("Enter a valid URL, for example http://192.168.1.25:8000"); }
  if (!["http:", "https:"].includes(u.protocol) || !u.hostname || u.username || u.password || u.search || u.hash) {
    throw new Error("Use an http:// or https:// server URL without credentials, query strings, or fragments.");
  }
  return value.trim().replace(/\/+$/, "");
}
let win;
let configWin;
function openServerConfig() {
  if (configWin && !configWin.isDestroyed()) { configWin.focus(); return; }
  configWin = new BrowserWindow({
    width: 650, height: 590, minWidth: 580, minHeight: 520,
    title: "BizSuite Server Connection", parent: win || undefined,
    modal: !!win, resizable: true, autoHideMenuBar: true,
    icon: path.join(__dirname, "assets", "bizsuite.ico"),
    webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, "server-config-preload.js") }
  });
  configWin.loadFile(path.join(__dirname, "server-config.html"));
  configWin.on("closed", () => { configWin = null; });
}
function createMainWindow() {
  const apiBase = readApiBase();
  win = new BrowserWindow({
    width: 1280, height: 840, minWidth: 980, minHeight: 650,
    title: "BizSuite Manager", icon: path.join(__dirname, "assets", "bizsuite.ico"),
    autoHideMenuBar: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, "preload.js"), additionalArguments: [`--bizsuite-api-base=${apiBase}`] }
  });
  win.loadFile("index.html");
  win.on("closed", () => { win = null; });
  if (app.isPackaged && process.env.BIZSUITE_UPDATE_FEED_CONFIGURED === "1" && process.env.BIZSUITE_DISABLE_UPDATES !== "1") {
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.on("update-downloaded", () => {
      if (!win) return;
      dialog.showMessageBox(win, { type: "info", title: "BizSuite update ready", message: "A BizSuite software update has downloaded.", detail: "Restart BizSuite to install it.", buttons: ["Restart now", "Later"], defaultId: 0 })
        .then(r => { if (r.response === 0) autoUpdater.quitAndInstall(); });
    });
    autoUpdater.on("error", e => console.error("BizSuite updater:", e.message));
    setTimeout(() => autoUpdater.checkForUpdates().catch(e => console.error("Update check failed:", e.message)), 7000);
    setInterval(() => autoUpdater.checkForUpdates().catch(() => {}), 6 * 60 * 60 * 1000);
  }
}

ipcMain.handle("bizsuite:get-server-config", () => ({ apiBase: readSavedConfig() }));
ipcMain.handle("bizsuite:save-server-config", (_event, value) => {
  const apiBase = normalizeApiBase(value);
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify({ apiBase, savedAt: new Date().toISOString() }, null, 2), { encoding: "utf8", mode: 0o600 });
  return { ok: true, apiBase };
});
ipcMain.handle("bizsuite:test-server", async (_event, value) => {
  const apiBase = normalizeApiBase(value);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(apiBase + "/openapi.json", { signal: controller.signal });
    if (!response.ok) return { ok: false, message: `Server responded with HTTP ${response.status}. Check that this is the BizSuite API URL.` };
    const data = await response.json().catch(() => ({}));
    if (!data || !String(data.title || "").toLowerCase().includes("bizsuite")) {
      return { ok: false, message: "A server responded, but it does not appear to be the BizSuite API." };
    }
    return { ok: true, message: "Connected successfully to the BizSuite server." };
  } catch (e) {
    return { ok: false, message: "Could not reach the server. Check the URL, server status, firewall, and network. " + (e.name === "AbortError" ? "The request timed out." : "") };
  } finally { clearTimeout(timer); }
});
ipcMain.on("bizsuite:restart-app", () => { app.relaunch(); app.exit(0); });

const menu = Menu.buildFromTemplate([
  { label: "File", submenu: [
    { label: "Configure server connection…", click: openServerConfig, accelerator: "Ctrl+," },
    { type: "separator" }, { role: "reload" }, { role: "quit" }
  ]},
  { label: "Help", submenu: [
    { label: "About BizSuite", click: () => dialog.showMessageBox(win || configWin, { type: "info", title: "About BizSuite", message: "BizSuite Manager", detail: "BizSuite Professional Desktop\nConfigure the company server from File → Configure server connection." }) }
  ]}
]);
app.whenReady().then(() => {
  Menu.setApplicationMenu(menu);
  if (app.isPackaged && !readSavedConfig() && !process.env.BIZSUITE_API_URL) openServerConfig();
  else createMainWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) { if (app.isPackaged && !readSavedConfig() && !process.env.BIZSUITE_API_URL) openServerConfig(); else createMainWindow(); } });
});
app.on("window-all-closed", () => app.quit());
