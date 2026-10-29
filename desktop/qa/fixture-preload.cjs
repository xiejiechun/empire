const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("empire", {
  cancel: () => Promise.resolve(),
  read: (op, p) => ipcRenderer.invoke("read", op, p),
  command: (op, p, id) => ipcRenderer.invoke("command", op, p, id),
  status: () => Promise.resolve({ online: true, status: "隔离交互测试" }),
  close: () => ipcRenderer.invoke("close"),
});
