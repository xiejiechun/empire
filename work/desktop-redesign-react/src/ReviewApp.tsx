import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Button, ConfigProvider, Dropdown, Input, Modal, Segmented, Space, Tag, Tooltip, message, theme } from 'antd';
import type { InputRef } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AppstoreOutlined, ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, CloseOutlined, DatabaseOutlined, FileTextOutlined, FolderOpenOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MoonOutlined, QuestionCircleOutlined, SearchOutlined, SettingOutlined, SunOutlined } from '@ant-design/icons';
import DataWorkspace from './ReviewDataWorkspace';
import TaskWorkspace from './ReviewTaskWorkspace';
import { catalog, tasks } from './review-data';
import type { Screen } from './review-data';
import './review.css';
import ExitWorkspace from './ReviewExits';
import ResourceWorkspace,{ResourceProvider} from './ReviewResources';
import PlatformWorkspace,{PlatformProvider} from './ReviewPlatforms';
import {ArchivedWorkspace} from './ReviewRecords';
import './review-manager.css';

export default function ReviewApp() {
  const [dark,setDark]=useState(false);
  return <ConfigProvider locale={zhCN} componentSize="small" theme={{
    algorithm:[dark?theme.darkAlgorithm:theme.defaultAlgorithm,(seed,map)=>({...theme.compactAlgorithm(seed,map),fontSize:13,fontSizeSM:12,controlHeight:30,controlHeightSM:28,lineHeight:1.5})],
    token:{fontSize:13,borderRadius:5,fontFamily:'"Segoe UI", "Microsoft YaHei UI", sans-serif'},
    components:{Table:{cellPaddingBlockSM:4,cellPaddingInlineSM:12,cellPaddingBlockMD:8,cellFontSizeSM:13,headerBorderRadius:0},Button:{fontWeight:400},Tabs:{horizontalMargin:'0'},Splitter:{splitBarSize:7,splitTriggerSize:3}},
  }}><ResourceProvider><PlatformProvider><Shell dark={dark} onTheme={()=>setDark(!dark)} /></PlatformProvider></ResourceProvider></ConfigProvider>;
}

function Shell({dark,onTheme}:{dark:boolean;onTheme:()=>void}) {
  const {token}=theme.useToken();
  const [screen,setScreen]=useState<Screen>('catalog');
  const [catalogRequest,setCatalogRequest]=useState(0);
  const [compact,setCompact]=useState(true);
  const [collapsed,setCollapsed]=useState(false);
  const [category,setCategory]=useState('');
  const [taskFilter,setTaskFilter]=useState('all');
  const [taskSource,setTaskSource]=useState('');
  const [command,setCommand]=useState(false);
  const [query,setQuery]=useState('');
  const [messageApi,contextHolder]=message.useMessage();
  const input=useRef<InputRef>(null);
  const isTask=screen!=='catalog'&&screen!=='statements';
  const [archived,setArchived]=useState<string[]>(['rights','names']);
  const liveTasks=tasks.filter(t=>!archived.includes(t.id));
  const counts={all:liveTasks.length,active:liveTasks.filter(t=>['采集中','等待归档'].includes(t.state)).length,attention:liveTasks.filter(t=>['请求失败','来源缺口'].includes(t.state)).length,paused:liveTasks.filter(t=>t.state==='已暂停').length};
  const categories=[...new Set(catalog.map(t=>t.category))];
  const style={
    '--canvas':token.colorBgLayout,'--surface':token.colorBgContainer,'--raised':token.colorBgElevated,
    '--border':token.colorBorderSecondary,'--border-strong':token.colorBorder,'--text':token.colorText,'--muted':token.colorTextSecondary,
    '--blue':token.colorPrimary,'--blue-soft':token.colorPrimaryBg,'--selected':token.controlItemBgActive,'--hover':token.colorFillTertiary,
    '--amber':token.colorWarningText,'--amber-bg':token.colorWarningBg,
  } as CSSProperties;
  useEffect(()=>{Object.entries(style).forEach(([key,value])=>document.documentElement.style.setProperty(key,String(value)));},[dark]);
  const notify=(text:string)=>messageApi.info(text);
  const navigate=(next:Screen)=>{if(next==='catalog')setCatalogRequest(v=>v+1);setScreen(next);setCommand(false);setQuery('');};
  useEffect(()=>{
    const listener=(e:KeyboardEvent)=>{if(e.ctrlKey&&e.key.toLowerCase()==='k'){e.preventDefault();setCommand(v=>!v);}if(e.ctrlKey&&e.key.toLowerCase()==='b'){e.preventDefault();setCollapsed(v=>!v);}};
    document.addEventListener('keydown',listener);return()=>document.removeEventListener('keydown',listener);
  },[]);
  const commandItems=[{id:'catalog',label:'数据目录',type:'工作区'},{id:'statements',label:'利润表',type:'财务数据'},{id:'tasks',label:'采集任务',type:'工作区'},{id:'platforms',label:'采集出口',type:'采集管理'},{id:'identities',label:'身份管理',type:'采集管理'},{id:'resources',label:'共享资源',type:'采集管理'},{id:'archived',label:'已归档任务',type:'采集管理'},...catalog.filter(c=>c.id!=='income').map(c=>({id:`catalog:${c.category}`,label:c.name,type:c.source}))].filter(x=>`${x.label}${x.type}`.includes(query)).slice(0,9);
  return <div className={`review-app ${dark?'dark':''}`} style={style}>
    {contextHolder}
    <header className="global-header">
      <div className="wordmark"><span className="brand-glyph">E</span><strong>EMPIRE</strong><span className="wordmark-divider" /><span className="muted">研究工作空间</span></div>
      <nav className="global-navigation" aria-label="主导航"><button aria-current={!isTask?'page':undefined} onClick={()=>navigate('catalog')}><DatabaseOutlined />数据浏览</button><button aria-current={isTask?'page':undefined} onClick={()=>navigate('tasks')}><ClockCircleOutlined />采集管理{counts.attention>0&&<span className="nav-indicator">{counts.attention}</span>}</button></nav>
      <div className="global-tools"><button className="command-trigger" onClick={()=>setCommand(true)}><SearchOutlined /><span>搜索功能、数据</span><kbd>Ctrl K</kbd></button><Tag className="design-badge">设计评审 · 全目录预览</Tag><Tooltip title={dark?'切换浅色':'切换深色'}><Button aria-label={dark?'切换浅色主题':'切换深色主题'} type="text" icon={dark?<SunOutlined />:<MoonOutlined />} onClick={onTheme} /></Tooltip><Dropdown trigger={['click']} menu={{items:[{key:'compact',label:'紧凑密度',icon:compact?<CheckCircleOutlined />:undefined},{key:'comfortable',label:'舒适密度',icon:!compact?<CheckCircleOutlined />:undefined}],onClick:({key})=>setCompact(key==='compact')}}><Button type="text" aria-label="界面密度设置" icon={<SettingOutlined />} /></Dropdown><Tooltip title="本版设计说明"><Button type="text" aria-label="设计说明" icon={<QuestionCircleOutlined />} onClick={()=>Modal.info({title:'本轮设计评审',content:'本版涵盖任务、归档、运行记录、平台出口、共享资源与身份的管理设计。所有运行和财务数据均为示例；其他页面仍需逐类展开设计。正式业务程序尚未迁移。',okText:'知道了'})} /></Tooltip></div>
    </header>
    <div className={`review-body ${collapsed?'rail-mode':''}`}>
      <aside className="context-sidebar">
        <div className="sidebar-title"><strong>{collapsed?(isTask?<ClockCircleOutlined />:<DatabaseOutlined />):(isTask?'采集管理':'数据浏览')}</strong><Button type="text" aria-label={collapsed?'展开侧栏':'收起侧栏'} icon={collapsed?<MenuUnfoldOutlined />:<MenuFoldOutlined />} onClick={()=>setCollapsed(v=>!v)} /></div>
        {!collapsed&&<div className="sidebar-scroll">{isTask?<>
          <div className="sidebar-section">任务视图</div>
          <button className={`context-item ${screen==='tasks'&&taskFilter==='all'&&!taskSource?'active':''}`} onClick={()=>{setTaskFilter('all');setTaskSource('');navigate('tasks');}}><span>采集任务</span><span className="count">{tasks.length-archived.length}</span></button>
          <button className={`context-item ${screen==='archived'?'active':''}`} onClick={()=>navigate('archived')}><span>已归档任务</span><span className="count">{archived.length}</span></button>
          <div className="sidebar-section">运行与配置</div>
          {([['platforms','采集出口'],['identities','身份管理'],['resources','共享资源']] as const).map(([id,label])=><button key={id} className={`context-item ${screen===id?'active':''}`} onClick={()=>{navigate(id);}}><span>{label}</span></button>)}

        </>:<>
          <button className={`context-item ${screen==='catalog'&&!category?'active':''}`} onClick={()=>{setCategory('');navigate('catalog');}}><span><AppstoreOutlined />全部数据</span><span className="count">{catalog.length}</span></button>
          <div className="sidebar-section">业务分类</div>{categories.map(c=><button key={c} className={`context-item ${(screen==='catalog'&&category===c)||(screen==='statements'&&c===catalog.find(item=>item.id==='income')?.category)?'active':''}`} onClick={()=>{setCategory(c);navigate('catalog');}}><span>{c}</span><span className="count">{catalog.filter(r=>r.category===c).length}</span></button>)}
        </>}</div>}
      </aside>
      <main className="main-workspace">
        <div className="screen-container" hidden={isTask}><DataWorkspace catalogRequest={catalogRequest} view={screen==='catalog'?'catalog':'statements'} category={category} onCategory={setCategory} onOpen={()=>navigate('statements')} onBack={()=>navigate('catalog')} onTasks={()=>{setTaskFilter('attention');navigate('tasks');}} compact={compact} notify={notify} /></div>
        <div className="screen-container" hidden={screen!=='tasks'}><TaskWorkspace filter={taskFilter} source={taskSource} active={screen==='tasks'} archived={archived} onArchive={id=>setArchived(a=>[...a,id])} onResources={()=>navigate('resources')} onIdentity={()=>navigate('identities')}  compact={compact} onFilter={setTaskFilter} onSource={setTaskSource} onData={()=>navigate('statements')} notify={notify} /></div>
        <div className="screen-container" hidden={screen!=='archived'}><ArchivedWorkspace ids={archived} onRestore={id=>{setArchived(a=>a.filter(x=>x!==id));notify('任务已还原至预览列表，原启停状态保持。');}} /></div>
        <div className="screen-container" hidden={screen!=='resources'}><ResourceWorkspace notify={notify}/></div>
        <div className="screen-container" hidden={screen!=='platforms'}><ExitWorkspace/></div>
        <div className="screen-container" hidden={screen!=='identities'}><PlatformWorkspace initialIdentity={true} notify={notify}/></div>
      </main>
    </div>
    <footer className="review-statusbar"><span><span className="design-dot" />设计模式 · 全部为示例数据</span><span>未连接真实采集与数据库</span><span className="flex-gap" /><span>北京时间</span><span>Ctrl K 搜索 · Ctrl B 侧栏</span></footer>
    <Modal className="command-modal" open={command} onCancel={()=>setCommand(false)} footer={null} closable={false} width={620} afterOpenChange={open=>open&&input.current?.focus()}>
      <Input ref={input} size="large" prefix={<SearchOutlined />} aria-label="全局功能搜索" placeholder="搜索功能、数据名称或来源…" value={query} onChange={e=>setQuery(e.target.value)} allowClear />
      <div className="command-caption">{query?'搜索结果':'功能与数据'}</div><div className="command-results">{commandItems.length?commandItems.map((item,i)=><button key={`${item.id}:${i}`} onClick={()=>{if(item.id.startsWith('catalog:')){setCategory(item.id.slice(8));navigate('catalog');}else navigate(item.id as Screen);}}><FileTextOutlined /><span>{item.label}</span><small>{item.type}</small><ArrowRightOutlined /></button>):<div className="command-empty">没有匹配项，请尝试业务名称或来源。</div>}</div><div className="command-footer">Esc 关闭 · 选择入口后保留原页面状态</div>
    </Modal>
  </div>;
}