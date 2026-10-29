const {
  _electron,
} = require("C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const path = require("node:path"),
  assert = require("node:assert/strict"),
  fs = require("node:fs");
const root = path.resolve(__dirname, "..");
(async () => {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const app = await _electron.launch({
    executablePath: path.join(root, "node_modules/electron/dist/electron.exe"),
    args: [root],
    env,
  });
  const errors = [];
  try {
    const p = await app.firstWindow();
    p.on("pageerror", (e) => errors.push(e.message));
    p.setDefaultTimeout(15000);
    await p.waitForSelector(".shell");
    await p.waitForTimeout(1500);
    await p.waitForFunction(
      async () => !(await window.empire.status()).starting,
      {},
      { timeout: 30000 },
    );
    const status = await p.evaluate(() => window.empire.status());
    if (!status.online) {
      console.log(JSON.stringify({ mode: "blocked", status }, null, 2));
      assert.match(status.status, /已在当前用户下运行/);
      return;
    }
    await p.waitForSelector(".task-leaf", { timeout: 60000 });
    const directory = await p.evaluate(() =>
      window.empire.read("tasks.list", { limit: 100 }),
    );
    const archived = await p.evaluate(() =>
      window.empire.read("tasks.list", { archived: true, limit: 100 }),
    );
    const names = directory.rows.map((r) => r.id);
    const serviceChecks = await p.evaluate(async () => {
      const sites = await window.empire.read("sites.list", { limit: 100 });
      const exits = await window.empire.read("exits.read");
      const resources = await window.empire.read("resources.read");
      const identities = await window.empire.read("identities.catalog");
      const identity = identities.length
        ? await window.empire.read("identities.read", {
            platform: identities[0].id,
          })
        : null;
      const events = await window.empire.read("run.events", {
        ident: "ths-income",
      });
      return {
        sites: sites.total,
        exitDevices: exits.devices.length,
        resourceFields: resources.fields.length,
        identityPlatforms: identities.length,
        identityRows: identity?.total,
        identityWarning: identity?.warning || "",
        events: events.total,
        unlinked: events.unlinked_count,
      };
    });
    assert.ok(serviceChecks.sites > 0);
    assert.ok(serviceChecks.resourceFields >= 11);
    assert.ok(names.length > 24);
    assert.ok(names.includes("ths-income"));
    assert.ok(!names.includes("income"));
    await p.getByRole("textbox", { name: "搜索采集项" }).fill("ths-income");
    await p.waitForTimeout(1000);
    await p.locator(".task-leaf").first().click();
    await p.getByRole("tab", { name: "采集说明", exact: true }).click();
    await p.getByText("证券与市场", { exact: true }).waitFor();
    await p.getByRole("tab", { name: "运行与记录", exact: true }).click();
    await p.locator('.round-picker button').nth(1).click();
    assert.equal(await p.locator('.journal-summary').count(),1);
    assert.equal(await p.locator('.run-journal > .json-detail').count(),0);
    await p.locator('.round-picker button').first().click();
    await p.getByRole('textbox',{name:'搜索采集项'}).fill('');
    await p.waitForTimeout(1800);
    await p.locator('.context-item .count').first().filter({hasText:String(directory.total)}).waitFor();
    fs.mkdirSync(path.join(root, "qa-output"), { recursive: true });
    await p.screenshot({
      path: path.join(root, "qa-output/live-tasks.png"),
      animations: "disabled",
    });
    for (const name of [
      "跨任务记录",
      "站点访问规则",
      "采集出口",
      "共享资源",
      "身份管理",
      "运行状态",
    ]) {
      await p.getByRole("button", {name:"搜索功能"}).click();
      await p.locator(".command-results button").filter({hasText:name}).click();
      await p.waitForTimeout(1200);
      assert.ok(!(await p.locator("main").innerText()).includes("DEMO-"));
      if (await p.locator(".ant-drawer-close:visible").count()) {await p.locator(".ant-drawer-close:visible").click(); await p.waitForTimeout(400);}
    }
    await p.locator(".context-item").filter({hasText:"采集任务"}).click();
    assert.equal(await p.locator(".round-picker button").count(),3);
    for (const w of [1280, 1920]) {
      await app.evaluate(
        ({ BrowserWindow }, w) =>
          BrowserWindow.getAllWindows()[0].setContentSize(w, 950),
        w,
      );
      assert.ok(
        await p.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(root, "qa-output/live-read.json"),
      JSON.stringify(
        {
          taskCount: directory.total,
          archivedCount: archived.total,
          serviceChecks,
          taskIds: names,
          checks: [
            "真实任务目录",
            "专项说明",
            "七个管理入口只读",
            "1280/1920布局",
            "无脚本异常",
          ],
          errors,
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify(
        {
          message: "Live read checks passed",
          tasks: directory.total,
          archived: archived.total,
          serviceChecks,
        },
        null,
        2,
      ),
    );
  } finally {
    const p = (await app.windows())[0];
    if (p) {
      await p.evaluate(() => window.empire.close()).catch(() => {});
    }
    await new Promise((resolve) =>
      app.process().exitCode !== null
        ? resolve()
        : app.process().once("exit", resolve),
    );
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
