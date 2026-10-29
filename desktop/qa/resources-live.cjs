// Read-only real backend verification. Close the existing desktop first.
const {_electron}=require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
 const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root,'--empire-config='+path.resolve(root,'../dist/EmpireDesktop/config.toml')],env});
 try{
  const p=await app.firstWindow();p.setDefaultTimeout(60000);
  await p.getByRole('button',{name:'共享资源',exact:true}).click();
  const box=p.getByRole('region',{name:'下载资源设置'});
  await box.getByRole('spinbutton').first().waitFor();
  const r=await p.evaluate(()=>window.empire.read('resources.read'));
  assert.equal(r.fields.length,2);assert.ok(r.live);
  assert.ok(Number.isInteger(r.live.active_requests));
  assert.ok(r.live.buffer_reserved_bytes>=0 && r.live.buffer_reserved_bytes<=r.live.buffer_limit_bytes);
  assert.equal(await box.getByRole('spinbutton').count(),2);
  await p.screenshot({path:path.join(root,'qa-output/resources-live.png')});
  console.log(JSON.stringify({fields:r.fields.map(f=>f.key),live:r.live,pending_restart:r.pending_restart,saved_values_unchanged:true}));
 }finally{
  const p=(await app.windows())[0];if(p)await p.evaluate(()=>window.empire.close()).catch(()=>{});
  await new Promise(r=>app.process().exitCode!==null?r():app.process().once('exit',r));
 }
})().catch(e=>{console.error(e);process.exitCode=1});
