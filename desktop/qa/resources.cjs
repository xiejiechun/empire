const {_electron}=require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
 const app=await _electron.launch({executablePath:path.resolve(__dirname,'../node_modules/electron/dist/electron.exe'),args:[path.join(__dirname,'resources-harness.cjs')],env});
 try{
  const p=await app.firstWindow();p.setDefaultTimeout(10000);
  await p.getByRole('button',{name:'共享资源',exact:true}).click();
  const box=p.getByRole('region',{name:'下载资源设置'});
  await box.getByRole('spinbutton').first().waitFor();
  assert.equal(await box.getByRole('spinbutton').count(),2);
  assert.equal(await box.getByText('生成容量草稿').count(),0);
  const count=box.getByRole('spinbutton').first();
  await count.fill('64');await p.waitForTimeout(3300);
  assert.equal(await count.inputValue(),'64');
  await box.getByRole('button',{name:'保存设置',exact:true}).click();
  await count.fill('32');await p.waitForTimeout(1200);
  assert.equal(await count.inputValue(),'32');
  assert.ok(await box.getByText('有未保存修改',{exact:true}).isVisible());
  await box.getByRole('button',{name:'撤销修改'}).click();
  assert.equal(await count.inputValue(),'64');
  await box.getByText('配置已保存，正常退出并重新打开软件后生效').waitFor();
  assert.ok((await box.getByRole('status').innerText()).includes('正在下载 3 个'));
  await p.screenshot({path:path.resolve(__dirname,'../qa-output/resources-simple.png')});
  await p.setViewportSize({width:720,height:800});
  assert.ok(await box.getByRole('button',{name:'保存设置',exact:true}).isVisible());
  console.log('PASS two controls, live status, refresh draft, save race, undo, restart notice, narrow layout');
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exit(1)});
