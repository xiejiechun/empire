import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Descriptions, Drawer, Dropdown, Form, Input, InputNumber, Modal, Progress, Segmented, Select, Space, Splitter, Switch, Table, Tabs, Tag, Timeline, Tree } from 'antd';
import { ArrowRightOutlined, CloseOutlined, DownOutlined, EllipsisOutlined, PauseOutlined, PlayCircleOutlined, SearchOutlined, SettingOutlined } from '@ant-design/icons';
import { defaultPlan, planText, tasks } from './review-data';
import type { Plan, Task } from './review-data';
import TaskRules, { ruleId, ruleFor } from './ReviewTaskRules';
import TaskRunJournal from './ReviewRunJournal';
import {RunsWorkspace} from './ReviewRecords';
import ResourceWorkspace from './ReviewResources';
import PlatformWorkspace from './ReviewPlatforms';
import { NoResults, RunBadge } from './review-shared';

type Props = { archived:string[]; onArchive:(id:string)=>void; onResources:()=>void; onIdentity:()=>void; filter: string; source: string; active: boolean; compact: boolean; onFilter: (v:string)=>void; onSource:(v:string)=>void; onData:()=>void; notify:(text:string)=>void };
export default function TaskWorkspace({ archived, onArchive, onResources, onIdentity, filter, source, active, compact, onFilter, onSource, onData, notify }: Props) {
  const [search,setSearch]=useState('');
  const [batch,setBatch]=useState(false),[checked,setChecked]=useState<React.Key[]>([]);
  const [freshIds,setFreshIds]=useState<string[]>([]);
  const [states,setStates]=useState<Record<string,Task['state']>>({});
  const taskRows=tasks.map(t=>({...t,state:states[t.id]||t.state,...(freshIds.includes(t.id)?{done:0,queued:0,pending:0,written:0}:{})}));
  const [context,setContext]=useState<'resources'|'records'|'rules'>();
  const [category,setCategory]=useState<string>();
  const [selected,setSelected]=useState('income');
  const [expanded,setExpanded]=useState<React.Key[]>(['platform:同花顺']);
  const [detailTab,setDetailTab]=useState('runs');
  const [planId,setPlanId]=useState<string>();
  const [saved,setSaved]=useState<Record<string,Plan>>(()=>Object.fromEntries(tasks.map(t=>[t.id,{...defaultPlan,mode:t.state==='采集中'?'interval':'daily',enabled:t.state!=='已暂停'}])));
  const [drafts,setDrafts]=useState<Record<string,Plan>>({});
  const [form]=Form.useForm<Plan>();
  const formValues=Form.useWatch([],form) as Plan|undefined;
  const results=taskRows.filter(t=>!archived.includes(t.id)&&(!source||t.source===source)&&(!category||t.category===category)&&`${t.name}${t.source}${ruleId(t.id)}`.toLowerCase().includes(search.toLowerCase())
    && (filter==='active'?['采集中','等待归档'].includes(t.state):filter==='attention'?['请求失败','来源缺口'].includes(t.state):filter==='paused'?t.state==='已暂停':filter==='disabled'?!saved[t.id].enabled:filter==='complete'?t.state==='已核验':filter==='gap'?t.state==='来源缺口':true));
  const current=results.find(t=>t.id===selected);
  useEffect(()=>{if(results.length&&!current)setSelected(results[0].id);},[filter,source,category,search,archived]);
  useEffect(()=>{if(!active)setPlanId(undefined);},[active]);
  const dirty=(id:string)=>drafts[id]&&JSON.stringify(drafts[id])!==JSON.stringify(saved[id]);
  const openPlan=(id:string)=>{setPlanId(id);form.setFieldsValue(drafts[id]||saved[id]);};
  const reset=()=>{onFilter('all');onSource('');setCategory(undefined);setSearch('');};
  const action=(verb:string,ids:React.Key[],enable=false)=>Modal.confirm({title:`${verb} ${ids.length} 个任务？`,content:verb==='暂停'?'停止当前采集并停用后续计划；保留断点与已归档数据。再次运行须启用并保存。':verb==='重新采集'?ruleFor(String(ids[0]))?.fresh||'新建采集批次，保留已归档数据。':enable?'启用选中任务并使用已保存配置；未保存草稿保留，运行中任务跳过。':'使用已保存计划与断点。所有操作仅改变本次预览。',okText:`演示${verb}`,cancelText:'取消',onOk:()=>{
    const outcome=ids.map(String).filter(id=>!id.startsWith('platform:')).map(id=>{const t=taskRows.find(t=>t.id===id)!;const skip=verb!=='暂停'&&(['采集中','等待归档'].includes(t.state)||(!enable&&!saved[id].enabled));
      if(!skip){if(verb==='重新采集')setFreshIds(old=>[...old,id]);setStates(old=>({...old,[id]:verb==='暂停'?'已暂停':'采集中'}));if(verb==='暂停'||enable)setSaved(old=>({...old,[id]:{...old[id],enabled:verb!=='暂停'}}));}
      return {id,name:t.name,result:skip?'跳过': '成功',reason:skip?'任务运行中、等待归档或尚未启用':verb==='暂停'?'已停用计划，保留断点':'已提交预览运行，使用已保存配置'};});
    Modal.info({title:`预览结果：成功 ${outcome.filter(r=>r.result==='成功').length} / 跳过 ${outcome.filter(r=>r.result==='跳过').length} / 失败 0`,width:680,content:<Table size="small" rowKey="id" pagination={{pageSize:6}} dataSource={outcome} columns={[{title:'任务',dataIndex:'name'},{title:'结果',dataIndex:'result'},{title:'说明',dataIndex:'reason'}]}/>});
  }});
  const treeData=[...new Set(results.map(t=>t.source))].map(platform=>({key:`platform:${platform}`,title:<span className="platform-tree-title"><strong>{platform}</strong><span className="platform-actions"><small>{results.filter(t=>t.source===platform).length}</small><Dropdown trigger={['click']} menu={{items:[{key:'run',label:'批量采集该平台任务'},{key:'pause',label:'批量暂停该平台任务'}],onClick:({key})=>action(key==='run'?'采集':'暂停',results.filter(t=>t.source===platform).map(t=>t.id),key==='run')}}><Button type="text" size="small" aria-label={`${platform}批量操作`} icon={<EllipsisOutlined/>} onClick={e=>e.stopPropagation()}/></Dropdown></span></span>,selectable:false,children:results.filter(t=>t.source===platform).map(t=>({key:t.id,title:<span className="task-tree-title"><span>{t.name}</span><Badge title={t.state} status={t.state==='请求失败'?'error':t.state==='来源缺口'||t.state==='等待归档'?'warning':t.state==='采集中'?'processing':t.state==='已暂停'?'default':'success'}/>{dirty(t.id)&&<span className="draft-dot" title="未保存草稿">•</span>}<small className="compact-task-progress" title={`${t.done} / ${t.total} 完整采集单元`}>{t.state==='采集中'?`${Math.floor(t.done/t.total*100)}%`:t.state==='等待归档'?'待归档':''}</small></span>}))}));
  useEffect(()=>{if(current)setExpanded(old=>Array.from(new Set([...old,`platform:${current.source}`])));},[current?.id]);
  return <div className="page-stack">
    <header className="page-heading-v2"><div className="heading-title"><div><h1>采集任务 <span className="title-count">{tasks.length-archived.length}</span></h1><span className="muted">查看进度、处理异常与管理执行计划</span></div></div><Space><Button onClick={()=>{setBatch(!batch);setChecked([]);}}>{batch?'结束批量选择':'批量操作'}</Button><Button onClick={()=>setContext('records')}>跨任务记录</Button></Space></header>
    <div className="task-directory-workspace fill">
      <aside className="task-directory"><div className="directory-tools"><Input aria-label="搜索采集项" placeholder="搜索平台、采集项或任务 ID" value={search} onChange={e=>setSearch(e.target.value)} allowClear prefix={<SearchOutlined/>}/><Select aria-label="采集项状态" value={filter} onChange={onFilter} options={[{value:'all',label:'全部状态'},{value:'attention',label:'需要处理'},{value:'active',label:'进行中'},{value:'paused',label:'已暂停'},{value:'disabled',label:'计划已停用'},{value:'complete',label:'已核验'},{value:'gap',label:'来源缺口'}]}/><Select aria-label="业务分类筛选" allowClear placeholder="全部业务分类" value={category} onChange={setCategory} options={[...new Set(tasks.map(t=>t.category))].map(value=>({value,label:value}))}/></div>{batch&&<Space wrap style={{padding:8}}><span>已选 {checked.length} 项</span><Button size="small" disabled={!checked.length} onClick={()=>action('采集',checked,true)}>批量启动</Button><Button size="small" disabled={!checked.length} onClick={()=>action('暂停',checked)}>批量暂停</Button></Space>}<div className="directory-caption"><span>平台 / 采集项</span><span>{results.length} 项</span></div><div className="directory-tree">{results.length?<Tree checkable={batch} checkedKeys={checked} onCheck={keys=>setChecked((Array.isArray(keys)?keys:keys.checked).filter(k=>!String(k).startsWith('platform:')))} blockNode showLine={{showLeafIcon:false}} expandedKeys={search||filter!=='all'?treeData.map(t=>t.key):expanded} onExpand={setExpanded} selectedKeys={current?[current.id]:[]} onSelect={keys=>keys.length&&setSelected(String(keys[0]))} treeData={treeData}/>:<NoResults reset={reset}/>}</div><div className="directory-footer">进度按完整采集单元计算；满格仍可能待归档</div></aside>
      <section className="workspace-surface task-focus">
        {current?<><div className="focused-task-heading"><div><span className="eyebrow">{current.source} / {current.category}</span><h2>{current.name} <RunBadge state={current.state}/></h2><span className="muted">{planText(saved[current.id])}</span></div><Space><Button type="primary" icon={<PlayCircleOutlined />} disabled={!current||!saved[current.id].enabled||['采集中','等待归档'].includes(current.state)} onClick={()=>current&&action(current.state==='请求失败'?'继续采集':'采集',[current.id])}>{current?.state==='来源缺口'?'检查更新':current?.state==='请求失败'?'继续采集':current?.state==='采集中'?'任务正在运行':current?.state==='等待归档'?'等待归档完成':'立即采集'}</Button>{current.id==='income'&&<Button onClick={onData}>查看数据</Button>}<Button onClick={()=>openPlan(current.id)} icon={<SettingOutlined/>}>执行计划{dirty(current.id)?' · 未保存':''}</Button><Dropdown trigger={['click']} menu={{items:[{key:'fresh',label:'重新采集',disabled:!saved[current.id].enabled||['采集中','等待归档'].includes(current.state)},{key:'pause',label:'暂停并停用计划',disabled:!saved[current.id].enabled&&current.state==='已暂停'},{key:'archive',label:'归档任务'}],onClick:({key})=>key==='fresh'?action('重新采集',[current.id]):key==='pause'?action('暂停',[current.id]):Modal.confirm({title:`归档“${current.name}”？`,content:'停止计划并保留配置、断点与数据；这里只改变预览。',okText:'归档',cancelText:'取消',onOk:()=>onArchive(current.id)})}}><Button aria-label="当前采集项更多操作" icon={<EllipsisOutlined/>}/></Dropdown></Space></div>
              <Tabs activeKey={detailTab} onChange={setDetailTab} className="detail-tabs" items={[
                {key:'runs',label:'运行与记录',children:<TaskRunJournal key={current.id} task={{...current,next:!saved[current.id].enabled?'未安排（计划已停用）':saved[current.id].mode==='manual'?'仅手动，无自动执行':planText(saved[current.id])}}/>},
                {key:'access',label:'资源与身份',children:<div className="task-access"><div><strong>下载资源 · 全局共享</strong><p>项目使用统一下载窗口、缓冲与单响应限制。</p><Button onClick={()=>setContext('resources')}>查看与配置共享资源</Button></div><div><strong>身份与网络 · 平台共享</strong><p>站点访问规则由同平台任务共享，身份按固定设备绑定。</p><Space><Button onClick={()=>setContext('rules')}>站点访问规则</Button>{current.source==='同花顺'&&<Button onClick={onIdentity}>查看平台身份</Button>}</Space></div><div><strong>当前计划</strong><p>{planText(saved[current.id])}</p><Button onClick={()=>openPlan(current.id)}>编辑执行计划</Button></div></div>},
                {key:'rules',label:'采集说明',children:<TaskRules task={{...current,next:!saved[current.id].enabled?'未安排（计划已停用）':saved[current.id].mode==='manual'?'仅手动，无自动执行':planText(saved[current.id])}}/>},
              ]} />
        </>:<NoResults reset={reset}/>}
      </section>
    </div>
    <Drawer className="task-context-drawer" open={!!context} onClose={()=>setContext(undefined)} size="min(1240px, 95vw)" title={`${current?.name||'当前任务'} / ${context==='resources'?'共享下载资源':context==='records'?'跨任务记录':'站点访问规则'}`}><div hidden={context!=='resources'} className="context-workspace"><ResourceWorkspace notify={notify}/></div><div hidden={context!=='records'} className="context-workspace"><RunsWorkspace notify={notify}/></div><div hidden={context!=='rules'} className="context-workspace"><PlatformWorkspace notify={notify} rulesOnly initialSource={current?.source}/></div></Drawer>
    <Drawer className="review-plan" open={!!planId} size={470} onClose={()=>setPlanId(undefined)} title={<div><span className="eyebrow">执行计划</span><h3>{tasks.find(t=>t.id===planId)?.name}</h3></div>} footer={<div className="plan-savebar"><span className={planId&&dirty(planId)?'unsaved':'muted'}>{planId&&dirty(planId)?'有未保存的修改':'计划已保存于本次预览'}</span><Space><Button disabled={!planId||!dirty(planId)} onClick={()=>{if(planId){form.setFieldsValue(saved[planId]);setDrafts(p=>{const n={...p};delete n[planId];return n;});}}}>撤销</Button><Button type="primary" disabled={!planId||!dirty(planId)} onClick={async()=>{if(!planId)return;try{const p=await form.validateFields();setSaved(old=>({...old,[planId]:{...saved[planId],...p}}));setDrafts(old=>{const next={...old};delete next[planId];return next;});notify('预览计划已保存。真实任务配置未改变。');}catch{}}}>保存计划</Button></Space></div>}>
      <div className="plan-summary"><Badge status="processing" text="计划预览" /><strong>{planText({...defaultPlan,...formValues})}</strong><span>关闭面板保留草稿；保存后更新本次预览。</span></div>
      <Form form={form} layout="vertical" initialValues={defaultPlan} onValuesChange={(_,all)=>planId&&setDrafts(old=>({...old,[planId]:{...saved[planId],...all}}))}>
        <div className="form-section-title">执行安排</div><Form.Item name="enabled" label="启用任务" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="mode" label="执行方式"><Segmented block options={[{value:'daily',label:'每天定时'},{value:'interval',label:'固定间隔'},{value:'manual',label:'仅手动'}]} /></Form.Item>
        {formValues?.mode==='daily'&&<Form.Item name="time" label="每天执行时间 · 北京时间" rules={[{required:true,message:'请选择执行时间'}]}><Input type="time" aria-label="每日执行时间" /></Form.Item>}
        {formValues?.mode==='interval'&&<Form.Item name="interval" label="每次任务结束后等待（秒）" rules={[{required:true,message:'请输入等待秒数'}]} extra="不从启动时计时，同一任务不会重叠。"><InputNumber min={1} max={2592000} precision={0} style={{width:'100%'}} changeOnWheel={false} /></Form.Item>}
        <div className="form-section-title">网络与重试</div><Form.Item name="network" label="网络方式" extra="从下一轮采集生效，不中断当前请求。"><Select options={[{value:'proxy_fallback',label:'代理优先，可回退直连'},{value:'proxy_only',label:'仅使用代理'},{value:'direct',label:'本机直连'}]} /></Form.Item>
        <Form.Item name="retries" label="单次请求失败重试次数"><InputNumber min={0} max={100} precision={0} changeOnWheel={false} style={{width:'100%'}} /></Form.Item>
      </Form><div className="preview-inline-note">设计预览 · 不连接真实采集服务</div>
    </Drawer>
  </div>;
}