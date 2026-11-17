const {app,BrowserWindow,ipcMain}=require('electron');
const path=require('node:path');
let saved={max_parallel_downloads:128,buffer_budget_bytes:512*1048576};
const active={...saved};
let fail=false;
let healthFailed=false;
let healthPartial=false;
ipcMain.handle('read',(_e,op)=>{
 if(op==='health.read') {
  if(healthFailed) throw Error('运行状态暂不可用');
  return {plugins:[
   {id:'dataset.astock',state:'RUNNING',health:{compute:healthPartial?{active:2}:{active:2,waiting:3}}},
   {id:'pipeline.archive',state:'RUNNING',health:healthPartial?{ready_pending:17}:{ready_pending:17,staging_batches:1,queue_sample_age_seconds:8}}
  ]};
 }
 if(op==='resources.read') return {saved,active,pending_restart:JSON.stringify(saved)!==JSON.stringify(active),
  live:{active_requests:3,buffer_reserved_bytes:24*1048576,buffer_limit_bytes:512*1048576,waiting:2,
   effective_download_window:96,download_admission_waiting:5,download_feedback_reason:'归档积压'},
  fields:[{key:'max_parallel_downloads',unit:'个',scale:1,minimum:1,maximum:4096},
   {key:'buffer_budget_bytes',unit:'MiB',scale:1048576,minimum:1048576,maximum:4096*1048576}]};
 return {rows:[],total:0,plugins:[]};
});
ipcMain.handle('command',async(_e,op,p)=>{
 if(op==='fixture.health-fail') {healthFailed=p.value;return {};}
 if(op==='fixture.health-partial') {healthPartial=p.value;return {};}
 await new Promise(r=>setTimeout(r,800));
 if(op==='resources.save') {if(fail) throw Error('保存失败');saved={...p.values};}
 return {message:'已保存'};
});
ipcMain.handle('close',()=>app.quit());
app.whenReady().then(()=>{
 const w=new BrowserWindow({width:1100,height:800,show:true,webPreferences:{preload:path.join(__dirname,'fixture-preload.cjs'),contextIsolation:true,sandbox:true}});
 w.loadFile(path.join(__dirname,'../dist/index.html'));
});
