const { app, BrowserWindow, ipcMain, Menu, session } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const { Backend } = require("./transport.cjs");
const { backendArgs } = require("./launch-options.cjs");
app.setName("Empire");
app.setPath("userData", path.join(app.getPath("appData"), "EmpireDesktop"));
let window,
  backend,
  closing = false,
  closed = false,
  connected = false,
  status = "正在连接现有采集服务";
const reads = new Set([
  "preview.catalog",
  "preview.read",
  "health.read",
  "run.events",
  "tasks.list",
  "task.read",
  "collection.rules.read",
  "records.list",
  "error.read",
  "sites.list",
  "exits.read",
  "resources.read",
  "identities.catalog",
  "identities.read",
]);
const writes = new Set([
  "collection.policy.save",
  "collection.run",
  "collection.pause",
  "collection.batch",
  "collection.archive",
  "errors.clear",
  "sites.save",
  "resources.save",
  "identity.service",
]);
function trusted(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame
  )
    throw Error("无效的桌面调用");
}
async function close() {
  if (closing || closed) return;
  closing = true;
  status = "正在等待采集、归档及数据库连接正常退出";
  try {
    if (backend && !backend.dead) {
      await backend.ready;
      await backend.request("desktop.shutdown");
      await new Promise((resolve) =>
        backend.child.exitCode !== null
          ? resolve()
          : backend.child.once("exit", resolve),
      );
    }
    closed = true;
    app.quit();
  } catch (e) {
    status = e.message;
    closing = false;
    if (backend?.dead) {
      closed = true;
      app.quit();
    }
  }
}
ipcMain.handle("empire:read", async (e, op, params, scope) => {
  trusted(e);
  if (scope !== undefined && (typeof scope !== "string" || scope.length > 100))
    throw Error("无效查询范围");
  if (!reads.has(op) || closing) throw Error("操作不可用");
  await backend.ready;
  return backend.request(op, params, undefined, scope);
});
ipcMain.handle("empire:cancel", async (e, scope) => {
  trusted(e);
  if (typeof scope !== "string" || scope.length > 100)
    throw Error("无效查询范围");
  return backend.cancel(scope);
});
ipcMain.handle("empire:command", async (e, op, params, id) => {
  trusted(e);
  if (!writes.has(op) || closing || typeof id !== "string" || !id)
    throw Error("操作不可用");
  await backend.ready;
  return backend.request(op, params, id);
});
ipcMain.handle("empire:status", (e) => {
  trusted(e);
  return {
    status,
    online: connected && !!backend && !backend.dead,
    starting: !!backend && !backend.dead && !connected,
    closing,
  };
});
ipcMain.handle("empire:close", (e) => {
  trusted(e);
  void close();
});
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      window.restore();
      window.focus();
    }
  });
  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    session.defaultSession.setPermissionRequestHandler((_w, _p, reply) =>
      reply(false),
    );
    const root = path.resolve(__dirname, "../..");
    const executable = app.isPackaged
      ? path.join(path.dirname(app.getPath("exe")), "EmpireBackend.exe")
      : path.join(root, ".venv", "Scripts", "python.exe");
    const args = backendArgs(app.isPackaged, process.argv);
    const child = spawn(executable, args, {
      cwd: app.isPackaged ? path.dirname(app.getPath("exe")) : root,
      windowsHide: true,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    backend = new Backend(child);
    backend.on("offline", (message) => {
      status = message;
    });
    backend.ready
      .then(() => {
        connected = true;
        status = "已连接本地后端 · 服务状态以实际查询为准";
      })
      .catch((e) => (status = e.message));
    window = new BrowserWindow({
      width: 1600,
      height: 1000,
      minWidth: 1100,
      minHeight: 720,
      show: false,
      title: "Empire · 采集管理",
      icon: path.join(root, "src/empire/desktop/assets/empire.ico"),
      backgroundColor: "#f5f5f5",
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (e) => e.preventDefault());
    window.loadFile(path.join(__dirname, "../dist/index.html"));
    window.once("ready-to-show", () => window.show());
    window.on("close", (e) => {
      if (!closed) {
        e.preventDefault();
        void close();
      }
    });
  });
  app.on("before-quit", (e) => {
    if (!closed) {
      e.preventDefault();
      void close();
    }
  });
  app.on("window-all-closed", () => {
    if (closed) app.quit();
  });
}
