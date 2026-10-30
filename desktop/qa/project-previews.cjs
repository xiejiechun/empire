/* Project-owned preview QA. --mock never starts a Python runtime or connects to stores.
 * --live starts the real desktop and must be run only after its existing instance closes.
 * Evidence contains counts/identifiers only, never stored rows or connection settings. */
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."), output = path.join(root, "qa-output");
const longText = "长期保留来源说明、单位、缺失值与全部业务明细。".repeat(18);

function exampleCatalog() {
  const { execFileSync } = require("node:child_process");
  const source = [
    "import json,sys", "sys.stdout.reconfigure(encoding='utf-8')",
    "from empire.bootstrap import build_manager", "from empire.core.config import load_config",
    "from empire.desktop_bridge.preview import catalog",
    "manager=build_manager(load_config('config/app.example.toml'))",
    "tasks=manager.entries['collection.control'].plugin.definitions",
    "print(json.dumps([dict(id=k,name=t.name,source=t.rate_group,source_name=t.source_name,category=t.category,views=catalog(k)) for k,t in tasks.items()],ensure_ascii=False))",
  ].join("\n");
  return JSON.parse(execFileSync(path.join(root, "../.venv/Scripts/python.exe"), ["-c", source], {
    cwd: path.join(root, ".."), encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" },
    windowsHide: true,
  }));
}

function fieldValue(column, i) {
  const k = column.key;
  if (/unified_code|security/.test(k)) return "000001.SZ";
  if (k === "code") return "000001";
  if (k === "market") return "SZ";
  if (k === "report_key" || k === "record_key") return String(i + 1).repeat(64);
  if (/date$|_day$/.test(k)) return i ? "2026-06-30" : "2026-09-30";
  if (/time$|_at$/.test(k)) return "2026-10-28T15:30:00+08:00";
  if (/name|title|reason|description|brief|introduction|text/.test(k)) return i ? "另一条来源记录" : "测试业务记录";
  if (column.kind === "boolean" || k === "is_trade") return i === 0;
  if (column.kind === "number" || /amount|price|close|open|high|low|quantity|ratio|shares|volume/.test(k)) return i ? null : "123456789.012345";
  return ["status", "availability"].includes(k) ? "present" : String(i + 1);
}

function fixtureRows(spec, params) {
  const columns = spec.columns || [], renderer = spec.renderer;
  const base = (i) => ({ ...Object.fromEntries(columns.map((c) => [c.key, fieldValue(c, i)])),
    unified_code: params.filters?.code === "600000" ? "600000.SH" : "000001.SZ",
    code: "000001", name: "测试证券", report_key: String(i + 1).repeat(64), record_key: String(i + 1).repeat(64),
    report_date: i ? "2026-06-30" : "2026-09-30", theme_id: "1", index_code: "000001", industry_code: "881101",
    citation_key: "1".repeat(64), group_key: "1".repeat(64), plan_id: "1", list_date: i ? "2026-10-27" : "2026-10-28",
    source_dates: ["2026-10-27", "2026-10-28"], holder: i ? "测试第二位解禁股东" : "测试第一位解禁股东",
  });
  let rows = [base(0), base(1)];
  if (renderer === "statement") rows = rows.map((r, i) => ({ ...r, market: "SZ", currency: "CNY",
    period_basis: "year_to_date", announcement_date: null,
    fields: { "*营业总收入": { value: i ? "200" : "123456789.012345", resolution: "0.000001" },
      "*净利润": i ? { value: "0", resolution: "1" } : null,
      "其中：非常长的财报科目，用于验证横向报告期和完整科目不会被截断": { value: "-10.15", resolution: "0.01" },
      ...(i ? { "上期独有科目": { value: "9", resolution: "1" } } : {}) },
  }));
  if (renderer === "prices") rows = [
    { ...base(0), trade_date: "2026-10-28", open: "9.1", high: "10.2", low: "9", close: "10", volume_shares: "100000", amount_yuan: "980000" },
    { ...base(1), trade_date: "2026-10-27", open: "8", high: "9", low: "7.5", close: "8.5", volume_shares: "200000", amount_yuan: "1700000" },
  ];
  if (renderer === "prices" && params.filters?.security === "000002.SZ") rows[0].close = "";
  if (renderer === "calendar") rows = [{ trade_date: "2026-10-01", is_trade: false }, { trade_date: "2026-10-09", is_trade: true }];
  if (renderer === "calendar" && params.filters?.month === "2026-11") rows = [
    { trade_date: "2026-11-01", is_trade: true }, { trade_date: "2026-11-01", is_trade: false },
    { trade_date: "2026-11-02", is_trade: "invalid" }, { trade_date: "2026-10-09", is_trade: true },
    { trade_date: "2026-11-03", is_trade: false },
  ];
  if (renderer === "news") rows = rows.map((r, i) => ({ ...r, news_id: String(i + 1), title: i ? "第二条快讯" : "财经新闻阅读反例", content: longText,
    published_at: "2026-10-28T10:10:10+08:00", source: "sina", is_important: i === 0 }));
  if (renderer === "holdings" && spec.hidden) rows = [{ ...base(0), kind: "top_holders", report_type: "periodic",
    total_quantity: "10000", total_ratio: "10", ratio_basis: "占总股本比例", quality_flags: 1,
    members: [{ member_group: "current", seq: 1, source_rank: "1", holder_name: "测试当期持有人", quantity: "10000", ratio: null, change_label: "新进" },
      { member_group: "exited", seq: 1, source_rank: null, holder_name: "测试退出持有人", quantity: "0", ratio: "0", change_label: "退出" }],
  }];
  if (renderer === "hotlist" && spec.hidden) rows = [{ ...base(0), list_date: params.filters.day,
    detail_status: params.filters.day === "2026-10-27" ? "source_empty" : "present",
    reasons: [{ seq: 1, reason_code: "01", reason: "日涨幅偏离值达到7%", volume: "100000", turnover: "980000", close_price: "10", change_pct: "10" }],
    seats: [{ seq: 1, reason_code: "01", side: "B", seat_rank: 1, seat_name: "测试买入营业部", buy_amount: "10000", sell_amount: null, net_amount: "10000" },
      { seq: 2, reason_code: "01", side: "S", seat_rank: 1, seat_name: "测试卖出营业部", buy_amount: null, sell_amount: "9000", net_amount: "-9000" }],
  }];
  if (renderer === "reason") rows = [{ ...base(0), trade_date: "2026-10-28", availability: "present", reason_text: longText }];
  if (renderer === "themes") rows = rows.map((r) => ({ ...r, name: "测试题材", parent_id: null,
    category_name: "产业链分类", stock_name: "测试证券", reason: longText, brief: "题材摘要", introduction: longText }));
  if (params.ident === "tdx-additional-issues") rows = rows.map((r, i) => {
    const detail = { ...Object.fromEntries((spec.detail_columns || []).map((c) => [c.key, fieldValue(c, i)])),
      availability: "available", remark: "测试发行完整明细" };
    return { ...r, detail: i ? { availability: "unavailable", last_available: detail } : detail };
  });
  return rows;
}

async function mockMain() {
  const { app, BrowserWindow, ipcMain } = require("electron");
  const tasks = JSON.parse(fs.readFileSync(process.env.EMPIRE_PREVIEW_QA_CATALOG, "utf8"));
  globalThis.previewQaCalls = [];
  const policy = { enabled: false, mode: "manual", interval_seconds: 3600, daily_time: "18:00", request_retries: 2, use_proxy: true, proxy_fallback: true };
  ipcMain.handle("read", async (_event, op, params = {}) => {
    if (op.startsWith("preview.")) globalThis.previewQaCalls.push({ op, ...params });
    if (op === "tasks.list") {
      const rows = params.archived ? [] : tasks.filter((t) => !params.query || (t.id + t.name).includes(params.query));
      return { rows: rows.map((t) => ({ ...t, state: "disabled", enabled: false })), total: rows.length, categories: [...new Set(tasks.map((t) => t.category))] };
    }
    if (op === "task.read") return { ...tasks.find((t) => t.id === params.ident), policy, last_status: "disabled", active: null, progress: {} };
    if (op === "preview.catalog") return tasks.find((t) => t.id === params.ident)?.views || [];
    if (op === "preview.read") {
      const spec = tasks.find((t) => t.id === params.ident)?.views.find((v) => v.id === params.view);
      assert.ok(spec, "mock view is registered");
      const filters = params.filters || {}, required = (spec.filter_specs || []).filter((f) => f.required && !filters[f.key]);
      if (required.length) return { rows: [], next: null, required: true, message: "请先填写" + required.map((f) => f.label).join("、") };
      await new Promise((resolve) => setTimeout(resolve, filters.code === "600000" ? 900 : 35));
      if (filters.code === "999999") throw Error("隔离查询失败反例");
      if (filters.code === "888888") return { rows: [], next: null, message: "没有归档记录；不代表已采齐" };
      return { rows: fixtureRows(spec, params), next: JSON.parse(params.cursor || "null") === null && !spec.hidden && spec.renderer !== "calendar" ? "fixture-next" : null,
        message: "隔离样本，不是实采证据", storage: spec.id === "live" ? "Redis 盘中快照" : "已归档数据",
        context: { month: filters.month || "2026-10", ...(spec.renderer === "pool" || spec.id === "details" ? {
          head: { theme_id: "1", name: "测试题材", brief: "完整题材摘要", introduction: longText, source_total: 2 },
        } : {}), complete: false },
      };
    }
    if (op === "records.list" || op === "run.events") return { rows: [], total: 0, unlinked_count: 0 };
    if (op === "health.read") return { plugins: [] };
    return {};
  });
  ipcMain.handle("command", () => { throw Error("Preview QA must not issue commands"); });
  ipcMain.handle("close", () => app.quit());
  await app.whenReady();
  const window = new BrowserWindow({ width: 1540, height: 1000, show: true,
    webPreferences: { preload: path.join(__dirname, "fixture-preload.cjs"), backgroundThrottling: false, contextIsolation: true, nodeIntegration: false, sandbox: true } });
  await window.loadFile(path.join(root, "dist/index.html"));
}

function queryFilters(spec) {
  const values = { security: "000001.SZ", code: "000001", theme_id: "1", key: "1".repeat(64),
    day: "2026-10-28", stamp: "2026-10-28", month: "2026-10", selected_index: "000001" };
  return Object.fromEntries((spec.filters || []).filter((k) => values[k] && (k !== "code" || spec.renderer === "statement")).map((k) => [k, values[k]]));
}

async function main() {
  const live = process.argv.includes("--live");
  assert.ok(live || process.argv.includes("--mock"), "Choose --mock or --live explicitly");
  const { _electron } = require("C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
  fs.mkdirSync(output, { recursive: true });
  const fixtureFile = path.join(output, "project-preview-catalog.json");
  let catalog = exampleCatalog();
  assert.equal(new Set(catalog.map((t) => t.id)).size, catalog.length);
  assert.ok(catalog.length >= 49);
  fs.writeFileSync(fixtureFile, JSON.stringify(catalog, null, 2));
  const env = { ...process.env, EMPIRE_PREVIEW_QA_CATALOG: fixtureFile }; delete env.ELECTRON_RUN_AS_NODE;
  const app = await _electron.launch({ executablePath: path.join(root, "node_modules/electron/dist/electron.exe"),
    args: live ? [root, "--empire-config=" + path.join(root, "../dist/EmpireDesktop/config.toml")] : [__filename, "--harness"], env });
  const report = { mode: live ? "live" : "isolated", tasks: [], views: [], details: [], interactions: [], errors: [] };
  try {
    const p = await app.firstWindow(); p.setDefaultTimeout(20000);
    p.on("pageerror", (e) => report.errors.push(e.message));
    await p.waitForSelector(".task-leaf", { timeout: 60000 });
    if (live) {
      const actual = await p.evaluate(async () => {
        const active = await window.empire.read("tasks.list", { limit: 100 });
        const archived = await window.empire.read("tasks.list", { limit: 100, archived: true });
        const tasks = [...active.rows.map((t) => ({ ...t, archived: false })), ...archived.rows.map((t) => ({ ...t, archived: true }))];
        const result = [];
        for (const task of tasks) result.push({ ...task, views: await window.empire.read("preview.catalog", { ident: task.id }) });
        return result;
      });
      assert.deepEqual(actual.map((t) => t.id).sort(), catalog.map((t) => t.id).sort(), "Runtime project set differs from declared preview coverage");
      catalog = actual;
    }
    const search = p.getByRole("textbox", { name: "搜索采集项" });
    let archivedPage = false;
    async function selectTask(task) {
      if (!!task.archived !== archivedPage) {
        await p.getByRole("button", { name: task.archived ? /^已归档任务/ : /^采集任务/ }).first().click();
        archivedPage = !!task.archived;
      }
      await search.fill(task.id);
      await p.locator(".task-leaf").filter({ hasText: task.name }).first().waitFor();
      await p.getByRole("tab", { name: "数据预览", exact: true }).click();
      await p.locator(`[data-testid="project-preview"][data-project="${task.id}"]`).waitFor();
      return p.getByTestId("project-preview");
    }
    async function fillFilters(preview, spec) {
      const filters = queryFilters(spec);
      for (const field of spec.filter_specs || []) {
        if (filters[field.key] !== undefined) {
          const input = preview.getByLabel(field.label, { exact: true });
          if (await input.count()) await input.fill(filters[field.key]);
        }
      }
      await preview.getByRole("button", { name: "preview-search", exact: true }).click();
    }
    for (const task of catalog) {
      if (process.env.EMPIRE_PREVIEW_QA_PROJECT && task.id !== process.env.EMPIRE_PREVIEW_QA_PROJECT) continue;
      assert.ok(task.views.length, "No preview: " + task.id);
      console.log("Checking " + task.id);
      const preview = await selectTask(task);
      report.tasks.push(task.id);
      for (const spec of task.views.filter((v) => !v.hidden)) {
        if (task.views.filter((v) => !v.hidden).length > 1) await preview.getByRole("tab", { name: spec.title, exact: true }).click();
        await p.locator(`[data-testid="project-preview"][data-view="${spec.id}"]`).waitFor();
        await fillFilters(preview, spec);
        const content = preview.locator(`[data-preview-kind="${spec.renderer}"]`);
        await content.waitFor();
        const body = await preview.innerText();
        assert.ok(!body.includes("[object Object]"), "Object leaked: " + task.id + "/" + spec.id);
        assert.ok(!/\{\s*"(?:unified_code|record_key|report_key|fields)"\s*:/.test(body), "Raw JSON leaked");
        if (!live && spec.renderer === "calendar") {
          assert.equal(await content.getByRole("gridcell", { name: "2026-10-01 休市日", exact: true }).count(), 1);
          assert.equal(await content.getByRole("gridcell", { name: "2026-10-09 交易日", exact: true }).count(), 1);
          assert.equal(await content.getByRole("gridcell", { name: "2026-10-10 未知", exact: true }).count(), 1);
          report.interactions.push("calendar missing weekend remains unknown");
        }
        if (!live && spec.renderer === "prices") {
          const labels = await content.locator("svg circle title").allTextContents();
          assert.equal(labels.length, 2); assert.ok(labels[0].startsWith("2026-10-27") && labels[1].startsWith("2026-10-28"));
          report.interactions.push(task.id + " chart ascending dates");
        }
        if (!live && spec.renderer === "news") {
          assert.equal(await content.locator(".pv-news-body").innerText(), longText);
          report.interactions.push("news full text retained");
        }
        if (!live && task.id === "tdx-suspensions") {
          assert.ok(body.includes("2026-10-27") && body.includes("2026-10-28"));
          report.interactions.push("suspension source dates presented separately");
        }
        if (!live && task.id === "tdx-additional-issues") {
          await content.getByText("发行完整明细", { exact: true }).waitFor();
          await content.getByRole("list", { name: "事件列表" }).getByRole("button").nth(1).click();
          await content.getByRole("alert").filter({ hasText: "上次有效明细" }).waitFor();
          await content.getByText("上次有效发行明细", { exact: true }).waitFor();
          report.interactions.push("issue unavailable detail distinguished from previous valid version");
        }
        if (["ths-income", "cninfo-calendar", "ths-yuanhang-prices"].includes(task.id)) {
          await preview.getByRole("button", { name: "展开预览", exact: true }).click();
          await p.screenshot({ path: path.join(output, `project-preview-${report.mode}-${task.id}.png`), animations: "disabled" });
          await preview.getByRole("button", { name: "收起预览", exact: true }).click();
        }
        const args = { ident: task.id, view: spec.id, filters: queryFilters(spec), cursor: "null" };
        const data = await p.evaluate((args) => window.empire.read("preview.read", args), args);
        let second = null;
        if (data.next != null) {
          const next = await p.evaluate((args) => window.empire.read("preview.read", args), { ...args, cursor: JSON.stringify(data.next) });
          second = next.rows.length;
          await preview.getByRole("button", { name: "preview-next", exact: true }).click();
          await preview.locator(".preview-workspace-footer").filter({ hasText: "第 2 页" }).waitFor();
          await content.waitFor();
        }
        report.views.push({ task: task.id, view: spec.id, renderer: spec.renderer, rows: data.rows.length, second });
        if (spec.detailView && data.rows.length) {
          const detailSpec = task.views.find((v) => v.id === spec.detailView);
          assert.ok(detailSpec, "Missing registered detail target");
          const filters = Object.fromEntries(Object.entries(spec.detailFilters || {}).map(([filter, key]) => [filter, String(data.rows[0][key] ?? "")]));
          const detail = await p.evaluate((args) => window.empire.read("preview.read", args), { ident: task.id, view: detailSpec.id, filters, cursor: "null" });
          report.details.push({ task: task.id, view: detailSpec.id, rows: detail.rows.length });
          const open = preview.getByRole("button", { name: /^查看.*→$/ }).first();
          await open.click();
          await p.locator(`[data-testid="project-preview"][data-view="${detailSpec.id}"]`).waitFor();
          await preview.locator(`[data-preview-kind="${detailSpec.renderer}"]`).waitFor();
          if (!live && detailSpec.renderer === "holdings") {
            await preview.getByText("测试当期持有人", { exact: true }).first().waitFor();
            await preview.getByText("退出名单 1", { exact: true }).click();
            await preview.getByText("测试退出持有人", { exact: true }).first().waitFor();
            report.interactions.push(spec.id + " current and exited holders distinct");
          }
          if (!live && detailSpec.renderer === "hotlist") {
            await preview.getByText("测试买入营业部", { exact: true }).waitFor();
            await preview.getByText("卖出榜", { exact: true }).click();
            await preview.getByText("测试卖出营业部", { exact: true }).waitFor();
            report.interactions.push("hot list reason and both seat directions");
            await preview.getByRole("button", { name: "preview-back", exact: true }).click();
            await preview.getByRole("button", { name: /^查看.*→$/ }).nth(1).click();
            await preview.getByRole("alert").filter({ hasText: "上次有效的原因与席位" }).waitFor();
            report.interactions.push("source-empty seats explicitly labeled as previous valid data");
          }
          if (!live && task.id === "tdx-unlocks") {
            await preview.getByText("测试第一位解禁股东", { exact: true }).waitFor();
            await preview.getByText("测试第二位解禁股东", { exact: true }).waitFor();
            report.interactions.push("all unlock holders retained");
          }
          if (["ths-holders", "tdx-hot-list"].includes(task.id)) {
            await preview.getByRole("button", { name: "展开预览", exact: true }).click();
            await p.screenshot({ path: path.join(output, `project-preview-${report.mode}-${task.id}-${spec.id}.png`), animations: "disabled" });
            await preview.getByRole("button", { name: "收起预览", exact: true }).click();
          }
          await preview.getByRole("button", { name: "preview-back", exact: true }).click();
          await p.locator(`[data-testid="project-preview"][data-view="${spec.id}"]`).waitFor();
          if (data.next != null) await preview.locator(".preview-workspace-footer").filter({ hasText: "第 2 页" }).waitFor();
          await content.waitFor();
        }
      }
    }
    const statement = catalog.find((t) => t.id === "ths-income");
    let preview = await selectTask(statement);
    await fillFilters(preview, statement.views.find((v) => !v.hidden));
    if (!live) {
      const matrix = preview.getByRole("table", { name: "财报科目对照" });
      await matrix.waitFor();
      const text = await matrix.innerText();
      assert.ok(text.includes("上期独有科目") && text.replaceAll(",", "").includes("123456789.012345") && text.includes("—"));
      report.interactions.push("statement union of subjects, exact precision, missing distinct from zero");
      const events = catalog.find((t) => t.id === "tdx-earnings-forecast");
      preview = await selectTask(events);
      const spec = events.views.find((v) => !v.hidden), code = spec.filter_specs.find((f) => f.key === "code");
      const input = preview.getByLabel(code.label, { exact: true });
      await input.fill("600000"); await preview.locator("form").evaluate((form) => form.requestSubmit());
      await p.waitForTimeout(80);
      await input.fill("000001"); await preview.locator("form").evaluate((form) => form.requestSubmit());
      await p.waitForTimeout(1100);
      assert.ok(!(await preview.innerText()).includes("600000.SH"), "Late previous query overwrote current result");
      await input.fill("999999"); await preview.getByRole("button", { name: "preview-search", exact: true }).click();
      await preview.getByText(/隔离查询失败反例/).waitFor();
      assert.ok(!(await preview.innerText()).includes("测试业务记录"), "Failed new query shows old rows");
      report.interactions.push("query race and failure cannot show prior data as current");
      await input.fill("888888"); await preview.getByRole("button", { name: "preview-search", exact: true }).click();
      await preview.getByText(/不代表.*采齐/).first().waitFor();
      report.interactions.push("empty range does not certify collection completeness");
      const capital = catalog.find(t => t.id === "ths-capital");
      preview = await selectTask(capital);
      const views = capital.views.filter(v => !v.hidden);
      await preview.getByRole("tab", { name: views[0].title, exact: true }).click();
      await fillFilters(preview, views[0]);
      await preview.getByRole("button", { name: "preview-next", exact: true }).click();
      await preview.locator(".preview-workspace-footer").filter({ hasText: "第 2 页" }).waitFor();
      const field = views[0].filter_specs.find(f => f.key === "code");
      await preview.getByLabel(field.label, { exact: true }).fill("123456");
      await preview.getByRole("tab", { name: views[1].title, exact: true }).click();
      await preview.getByRole("tab", { name: views[0].title, exact: true }).click();
      assert.equal(await preview.getByLabel(field.label, { exact: true }).inputValue(), "123456");
      await preview.locator(".preview-workspace-footer").filter({ hasText: "第 2 页" }).waitFor();
      await preview.getByText("筛选已修改，查询后生效", { exact: true }).waitFor();
      report.interactions.push("column switch retains unapplied draft and applied page independently");
      const prices = catalog.find(t => t.id === "ths-yuanhang-prices");
      preview = await selectTask(prices);
      await preview.getByLabel("证券代码", { exact: true }).fill("000002.sz");
      await preview.getByRole("button", { name: "preview-search", exact: true }).click();
      await preview.locator(".pv-price-chart").waitFor();
      assert.equal(await preview.locator(".pv-price-chart circle").count(), 1, "Empty close plotted as zero");
      assert.equal(await preview.getByLabel("证券代码", { exact: true }).inputValue(), "000002.SZ");
      const cal = catalog.find(t => t.id === "cninfo-calendar");
      preview = await selectTask(cal);
      await preview.getByLabel("查询月份", { exact: true }).fill("2026-11");
      await preview.getByRole("button", { name: "preview-search", exact: true }).click();
      await preview.getByRole("gridcell", { name: "2026-11-01 未知", exact: true }).waitFor();
      await preview.getByRole("gridcell", { name: "2026-11-02 未知", exact: true }).waitFor();
      const metrics = await preview.locator(".pv-metric").allTextContents();
      assert.ok(metrics.some(t => /未取得数据29/.test(t)), JSON.stringify(metrics));
      report.interactions.push("empty price, duplicate/invalid/out-of-month calendar records retain unknown semantics");
    }
    const calendar = catalog.find((t) => t.id === "cninfo-calendar");
    preview = await selectTask(calendar);
    await fillFilters(preview, calendar.views.find((v) => !v.hidden));
    await preview.locator('[data-preview-kind="calendar"]').waitFor();
    await preview.getByRole("button", { name: "阅读说明", exact: true }).click();
    await p.getByText("数据口径与阅读说明", { exact: true }).waitFor();
    await preview.getByRole("button", { name: "阅读说明", exact: true }).click();
    report.interactions.push("reading notes open on demand without occupying the data workspace");
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1050, 760));
    await p.waitForTimeout(200);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 2, "Page overflows narrow window by " + overflow + "px");
    await p.screenshot({ path: path.join(output, "project-previews-" + report.mode + "-narrow.png"), animations: "disabled" });
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1540, 1000));
    await p.screenshot({ path: path.join(output, "project-previews-" + report.mode + ".png"), animations: "disabled" });
    await p.getByRole("button", { name: "切换主题", exact: true }).click();
    await p.screenshot({ path: path.join(output, "project-previews-" + report.mode + "-theme.png"), animations: "disabled" });
    await p.getByRole("button", { name: "切换主题", exact: true }).click();
    if (!live) {
      const calls = await app.evaluate(() => globalThis.previewQaCalls);
      report.requestCount = calls.filter((c) => c.op === "preview.read").length;
    }
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    const p = (await app.windows())[0];
    if (p) {
      await p.screenshot({ path: path.join(output, "project-previews-" + report.mode + "-failure.png"), animations: "disabled" }).catch(() => {});
      report.failure = { message: String(error), selection: await p.getByTestId("project-preview").getAttribute("data-view").catch(() => null) };
    }
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, "project-previews-" + report.mode + ".json"), JSON.stringify(report, null, 2));
    if (live) {
      const p = (await app.windows())[0]; if (p) await p.evaluate(() => window.empire.close()).catch(() => {});
      await new Promise((resolve) => app.process().exitCode !== null ? resolve() : app.process().once("exit", resolve));
    } else await app.close();
  }
  console.log(JSON.stringify({ mode: report.mode, projects: report.tasks.length, views: report.views.length, details: report.details.length, passed: report.passed }));
}

if (process.versions.electron && process.argv.includes("--harness")) mockMain().catch((e) => { console.error(e); process.exit(1); });
else main().catch((e) => { console.error(e); process.exitCode = 1; });
