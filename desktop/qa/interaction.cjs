const {
  _electron,
} = require("C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const path = require("node:path"),
  assert = require("node:assert/strict");
(async () => {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const root = path.resolve(__dirname, "..");
  const app = await _electron.launch({
    executablePath: path.join(root, "node_modules/electron/dist/electron.exe"),
    args: [path.join(__dirname, "harness.cjs")],
    env,
  });
  try {
    const p = await app.firstWindow();
    p.setDefaultTimeout(6000);
    await p.getByRole("button", { name: "执行计划", exact: true }).click();
    const retry = p.getByLabel("请求失败重试次数");
    await retry.fill("100");
    await p.getByRole("button", { name: "保存计划", exact: true }).click();
    await retry.fill("99");
    await p.waitForTimeout(1000);
    assert.equal(await retry.inputValue(), "99");
    assert.ok(
      await p
        .getByRole("button", { name: "保存计划", exact: true })
        .isEnabled(),
    );
    await p.locator(".ant-drawer-close").click();
    await p
      .locator(".focus-heading button")
      .filter({ hasText: "执行计划" })
      .click();
    assert.equal(await p.getByLabel("请求失败重试次数").inputValue(), "99");
    await p.getByRole("button", { name: /撤\s*销/ }).click();
    assert.equal(await p.getByLabel("请求失败重试次数").inputValue(), "100");
    await p.locator(".ant-drawer-close").click();
    await p.waitForTimeout(400);
    await p.getByRole("button", { name: "任务更多操作" }).click();
    await p.getByText("暂停并停用计划", { exact: true }).click();
    await p.getByRole("button", { name: "确认执行", exact: true }).click();
    await p.waitForTimeout(1000);
    assert.ok(
      await p
        .getByRole("button", { name: "立即采集", exact: true })
        .isDisabled(),
    );
    await p.getByRole("button", {name:"跨任务记录",exact:true}).click();
    await p.waitForTimeout(500);
    await p.locator(".ant-drawer-close").click();
    assert.ok(
      await p
        .getByRole("button", { name: "立即采集", exact: true })
        .isDisabled(),
    );
    assert.equal(await p.locator('.context-item').count(),5);
    assert.equal(await p.locator('.round-picker button').count(),3);
    await p.waitForTimeout(500);
    await p.screenshot({animations:'disabled',path:path.join(root,'qa-output','restored-tasks.png')});
    console.log(
      "Isolated UI checks passed: draft/save race, close/reopen, reset saved, pause gating",
    );
  } finally {
    await app.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
