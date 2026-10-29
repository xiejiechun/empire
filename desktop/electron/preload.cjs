const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld(
  "empire",
  Object.freeze({
    read: (operation, params = {}, scope) =>
      ipcRenderer.invoke("empire:read", operation, params, scope),
    cancel: (scope) => ipcRenderer.invoke("empire:cancel", scope),
    command: (operation, params = {}, operationId) =>
      ipcRenderer.invoke("empire:command", operation, params, operationId),
    status: () => ipcRenderer.invoke("empire:status"),
    close: () => ipcRenderer.invoke("empire:close"),
  }),
);
