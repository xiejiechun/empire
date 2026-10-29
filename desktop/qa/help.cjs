const { _electron } = require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const env = {...process.env}; delete env.ELECTRON_RUN_AS_NODE;
  const root = path.resolve(__dirname, '..');
  const app = await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[path.join(__dirname,'harness.cjs')],env});
  try {
    const p = await app.firstWindow(); p.setDefaultTimeout(10000);
    await p.locator('.global-navigation button').filter({hasText:'说明文档'}).click();
    await p.getByRole('heading',{name:'快速开始',exact:true}).waitFor();
    await p.getByLabel('搜索说明全文').fill('保存 计划');
    await p.locator('.help-index > button').filter({hasText:/^采集与计划$/}).click();
    await p.getByRole('heading',{name:'采集与计划',exact:true}).waitFor();
    await p.getByRole('button',{name:'返回上一篇'}).click();
    await p.getByRole('heading',{name:'快速开始',exact:true}).waitFor();
    await p.locator('.help-link').filter({hasText:'采集与计划'}).click();
    await p.getByRole('heading',{name:'采集与计划',exact:true}).waitFor();
    await p.getByLabel('搜索说明全文').fill('MySQL stock');
    await p.getByText('没有匹配说明，请减少关键词').waitFor();
    await p.getByLabel('搜索说明全文').fill('不存在的说明xyz');
    await p.getByText('没有匹配说明，请减少关键词').waitFor();
    await p.getByLabel('搜索说明全文').fill('');
    assert.equal(await p.locator('.help-index > button').count(), 5);
    assert.equal(await p.locator('.help-index').getByText('数据库参考').count(), 0);
    const names = await p.locator('.help-index > button').allTextContents();
    for (const name of names) {
      await p.locator('.help-index > button').filter({hasText:new RegExp('^'+name+'$')}).click();
      await p.getByRole('heading',{name,exact:true}).waitFor();
      const links = await p.locator('.help-link').allTextContents();
      assert.ok(links.every(link => !link.includes('数据库')));
    }
    await p.locator('.help-index > button').filter({hasText:/^快速开始$/}).click();
    await p.screenshot({path:path.join(root,'qa-output/help-wide.png')});
    await p.setViewportSize({width:720,height:800});
    await p.waitForTimeout(600);
    assert.ok(await p.locator('.help-reader').isVisible());
    await p.screenshot({path:path.join(root,'qa-output/help-narrow.png')});
    console.log('PASS offline help: guide, full-text search, article, back, help link, empty results, narrow layout');
  } finally {await app.close();}
})().catch(e=>{console.error(e);process.exit(1)});



