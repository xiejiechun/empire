const {_electron}=require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{for(const ident of ['ths-income','ths-yuanhang-limit-up-pool']){
 const root=process.cwd(),env={...process.env,EMPIRE_QA_RULES:path.join(root,'build/rules-'+ident+'.json')};delete env.ELECTRON_RUN_AS_NODE;
 const app=await _electron.launch({executablePath:path.join(root,'desktop/node_modules/electron/dist/electron.exe'),args:[path.join(root,'desktop/qa/harness.cjs')],env});
 try{const p=await app.firstWindow();await p.getByRole('tab',{name:'采集说明',exact:true}).click();await p.getByText('MySQL 业务表',{exact:true}).or(p.getByText('日终 MySQL 表',{exact:true})).waitFor();
 assert.equal(await p.locator('.collection-rules pre').count(),0);
 assert.equal(await p.getByText('Redis 断点 · Hash',{exact:true}).count(),0);
 if(ident.includes('limit-up'))await p.getByText('盘中数据',{exact:true}).waitFor();
 await p.screenshot({path:path.join(root,'build/collection-rules-'+ident+'.png')});
 await p.getByText('更多存储位置 · 断点、摘要、记录与配置',{exact:true}).click();await p.getByText('Redis 断点 · Hash',{exact:true}).waitFor();
 assert.ok(await p.locator('.collection-rules .ant-typography-copy').count()>5);
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1000,800));
 assert.equal(await p.locator('.collection-rules').evaluate(e=>e.scrollWidth>e.clientWidth+1),false);
 console.log(ident+': compact default, expandable keys, copy, narrow layout PASS');
 }finally{await app.close();}
}})().catch(e=>{console.error(e);process.exitCode=1});
