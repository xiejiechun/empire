const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("node:path");
let policy = {
  enabled: true,
  mode: "interval",
  interval_seconds: 3600,
  daily_time: "18:30",
  request_retries: 2,
  use_proxy: true,
  proxy_fallback: true,
};
let active = process.env.EMPIRE_QA_PROGRESS ? {run_id:'fixture-current',started_at:1793232000} : null;
const row = {
  id: "ths-income",
  name: "利润表",
  source: "ths",
  source_name: "同花顺",
  category: "财务",
  state: "complete",
  enabled: true,
};
ipcMain.handle("read", (_e, op, p) => {
  if (op === "collection.rules.read" && process.env.EMPIRE_QA_RULES)
    return JSON.parse(require("node:fs").readFileSync(process.env.EMPIRE_QA_RULES, "utf8"));
  if (op === "tasks.list")
    return {
      rows: process.env.EMPIRE_QA_PROGRESS ? [
        {...row,state:'running',progress:{completed_units:29,total_units:100}},
        {...row,id:'ths-holders',name:'前十大股东',state:'running',progress:{completed_units:54,total_units:100}},
      ] : [{ ...row, enabled: policy.enabled }],
      total: 1,
      offset: 0,
      categories: ["财务"],
    };
  if (op === "task.read")
    return {
      ...row,
      id: p.ident,
      policy,
      active,
      last_status: active ? "running" : "complete",
      unit_name: "只证券",
      progress: { completed_units: process.env.EMPIRE_QA_PROGRESS ? 29 : 2, total_units: process.env.EMPIRE_QA_PROGRESS ? 100 : 10 },
      latest_run: null,
    };
  if (op === "records.list") return { rows: [], total: 0 };
  if (op === "run.events") return { rows: [], total: 0, unlinked_count: 0 };
  if (op === "health.read") return { plugins: [] };
  return {};
});
ipcMain.handle("command", async (_e, op, p) => {
  await new Promise((r) => setTimeout(r, 600));
  if (op === "collection.policy.save") policy = p.policy;
  if (op === "collection.pause") {
    policy = { ...policy, enabled: false };
    active = null;
  }
  if (op === "collection.run")
    active = { run_id: "actual-fixture", started_at: 1 };
  return { message: "已保存" };
});
ipcMain.handle("close", () => app.quit());
app.whenReady().then(() => {
  const w = new BrowserWindow({
    width: 1600,
    height: 1000,
    show: true,
    webPreferences: {
      backgroundThrottling: false,
      preload: path.join(__dirname, "fixture-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  w.loadFile(path.join(__dirname, "../dist/index.html"));
});
