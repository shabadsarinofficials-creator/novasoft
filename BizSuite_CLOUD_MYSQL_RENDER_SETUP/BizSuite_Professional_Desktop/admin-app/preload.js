const { contextBridge } = require("electron");
const arg = process.argv.find((x) => x.startsWith("--bizsuite-api-base="));
const apiBase = arg ? arg.slice("--bizsuite-api-base=".length).replace(/\/$/, "") : "http://127.0.0.1:8000";
contextBridge.exposeInMainWorld("bizsuiteConfig", Object.freeze({ apiBase }));
