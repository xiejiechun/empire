const {_electron}=require('C:/Users/52948/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'), env={...process.env}; delete env.ELECTRON_RUN_AS_NODE;
 const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root,'--empire-config='+path.resolve(root,'../dist/EmpireDesktop/config.toml')],env});
 try {
  const p=await app.firstWindow(); const errors=[];p.on('pageerror',e=>errors.push(e.message));
  await p.waitForSelector('.shell');for(let i=0;i<60;i++){const s=await p.evaluate(()=>window.empire.status());if(s.online)break;await p.waitForTimeout(500);}
  await p.waitForSelector('.task-leaf',{timeout:60000});
  const result=await p.evaluate(async()=>{
   const status=await window.empire.status();if(!status.online)throw Error(status.status);
   const active=await window.empire.read('tasks.list',{limit:100}),archived=await window.empire.read('tasks.list',{archived:true,limit:100});
   const tasks=[...active.rows,...archived.rows]; const previews=[];
   for(const t of tasks){const v=await window.empire.read('preview.catalog',{ident:t.id});if(!v.length)throw Error('Missing preview '+t.id);previews.push(t.id);}
   const hot=await window.empire.read('preview.read',{ident:'tdx-hot-list',view:'records',filters:{},cursor:'null'});
   const resources=await window.empire.read('resources.read');
   return {tasks:tasks.length,previews:previews.length,hotListRows:hot.rows.length,resources:resources.fields.length};
  });
  assert.equal(result.tasks,49);assert.equal(result.previews,49);assert.equal(result.resources,2);
  assert.deepEqual(errors,[]);fs.mkdirSync(path.join(root,'qa-output'),{recursive:true});
  await p.screenshot({path:path.join(root,'qa-output/legacy-retired.png')});
  fs.writeFileSync(path.join(root,'qa-output/legacy-retired.json'),JSON.stringify({...result,errors},null,2));console.log(JSON.stringify(result));
 }finally{const p=(await app.windows())[0];if(p)await p.evaluate(()=>window.empire.close()).catch(()=>{});await new Promise(r=>app.process().exitCode!==null?r():app.process().once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
