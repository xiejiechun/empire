const {app,BrowserWindow,ipcMain}=require('electron');
const path=require('node:path');
let saved={max_parallel_downloads:128,buffer_budget_bytes:512*1048576};
const active={...saved};
let fail=false;
ipcMain.handle('read',(_e,op)=>{
 if(op==='resources.read') return {saved,active,pending_restart:JSON.stringify(saved)!==JSON.stringify(active),
  live:{active_requests:3,buffer_reserved_bytes:24*1048576,buffer_limit_bytes:512*1048576,waiting:2},
  fields:[{key:'max_parallel_downloads',unit:'个',scale:1,minimum:1,maximum:1024},
   {key:'buffer_budget_bytes',unit:'MiB',scale:1048576,minimum:1048576,maximum:4096*1048576}]};
 return {rows:[],total:0,plugins:[]};
});
ipcMain.handle('command',async(_e,op,p)=>{
 await new Promise(r=>setTimeout(r,800));
 if(op==='resources.save') {if(fail) throw Error('保存失败');saved={...p.values};}
 return {message:'已保存'};
});
ipcMain.handle('close',()=>app.quit());
app.whenReady().then(()=>{
 const w=new BrowserWindow({width:1100,height:800,show:true,webPreferences:{preload:path.join(__dirname,'fixture-preload.cjs'),contextIsolation:true,sandbox:true}});
 w.loadFile(path.join(__dirname,'../dist/index.html'));
});
