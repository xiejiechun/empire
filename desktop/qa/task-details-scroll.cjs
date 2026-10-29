// Regression for long task details using the actual Ant Design/Electron layout.
const {_electron}=require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const env={...process.env,EMPIRE_QA_LONG_RUN:'1'};delete env.ELECTRON_RUN_AS_NODE;
 const app=await _electron.launch({executablePath:path.resolve(__dirname,'../node_modules/electron/dist/electron.exe'),args:[path.join(__dirname,'harness.cjs')],env});
 try{
  const p=await app.firstWindow();
  await p.getByText('更多运行信息',{exact:true}).click();
  await p.getByText('运行详情底部标记',{exact:true}).waitFor();
  await p.waitForTimeout(400);
  for(const [width,height] of [[1366,768],[1920,1080],[3440,1369]]){
   await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setSize(...size),[width,height]);
   await p.waitForTimeout(200);
   const holder=p.locator('.detail-tabs > .ant-tabs-body-holder');
   await holder.evaluate(e=>e.scrollTop=0);
   const heading=await p.locator('.focused-task-heading').boundingBox();
   const directory=await p.locator('.task-directory').boundingBox();
   const bounds=await holder.boundingBox();
   await p.mouse.move(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
   await p.mouse.wheel(0,10000);
   await p.waitForFunction(()=>{const e=document.querySelector('.detail-tabs > .ant-tabs-body-holder');return e.scrollTop>0 && e.scrollTop+e.clientHeight>=e.scrollHeight-2;});
   assert.deepEqual(await p.locator('.focused-task-heading').boundingBox(),heading);
   assert.deepEqual(await p.locator('.task-directory').boundingBox(),directory);
   const tail=await p.getByText('运行详情底部标记',{exact:true}).boundingBox();
   assert.ok(tail.y>=bounds.y && tail.y+tail.height<=bounds.y+bounds.height);
   assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
   console.log(JSON.stringify({width,height,bottomReachable:true,headingAndDirectoryStable:true}));
  }
  await p.screenshot({path:path.join(__dirname,'../qa-output/task-details-scroll.png')});
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

