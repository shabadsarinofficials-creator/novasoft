const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("bizsuiteServer", Object.freeze({
  getConfig: () => ipcRenderer.invoke("bizsuite:get-server-config"),
  saveConfig: (url) => ipcRenderer.invoke("bizsuite:save-server-config", url),
  testConnection: (url) => ipcRenderer.invoke("bizsuite:test-server", url),
  restart: () => ipcRenderer.send("bizsuite:restart-app")
}));
