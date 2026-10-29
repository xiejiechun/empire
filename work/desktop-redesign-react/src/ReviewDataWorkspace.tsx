import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Checkbox, Drawer, Input, Pagination, Popover, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { TableColumnsType } from 'antd';
import { ArrowLeftOutlined, ArrowRightOutlined, FileTextOutlined, InfoCircleOutlined, SearchOutlined, TableOutlined } from '@ant-design/icons';
import Dataset from './ReviewDataset';
import {reports,reportNames} from './review-financial-fixtures';
import { catalog, periods, periodNames, statement } from './review-data';
import type { StatementRow } from './review-data';
import { NoResults, Tools, useStageHeight } from './review-shared';

type CatalogItem = typeof catalog[number];
type Props = { catalogRequest: number; view: 'catalog' | 'statements'; category: string; onCategory: (v: string) => void; onOpen: () => void; onBack: () => void; onTasks: () => void; compact: boolean; notify: (text: string) => void };
export default function DataWorkspace({ catalogRequest, view, category, onCategory, onOpen, onBack, onTasks, compact, notify }: Props) {
  const [reportKind,setReportKind]=useState('income');
  const [cell,setCell]=useState<{label:string;period:string;value:number|null}>();
  const [collapsedGroups,setCollapsedGroups]=useState<string[]>([]);
  const [linkedSecurity,setLinkedSecurity]=useState<string>();
  const [opened,setOpened]=useState<string>();
  useEffect(()=>setOpened(undefined),[category,view,catalogRequest]);
  const openItem=(r:CatalogItem)=>{if(['income','balance','cashflow'].includes(r.id)){setReportKind(r.id);setCollapsedGroups([]);setFind('');onOpen();}else setOpened(r.id);};
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<string>();
  const [page, setPage] = useState(1);
  const [security, setSecurity] = useState('000333');
  const [unit, setUnit] = useState('亿元');
  const [find, setFind] = useState('');
  const [showEmpty, setShowEmpty] = useState(true);
  const [visible, setVisible] = useState(periods);
  const [details, setDetails] = useState<CatalogItem | 'statement'>();
  const { ref, height } = useStageHeight();
  const securityName = security === '000333' ? '美的集团' : security === '600519' ? '贵州茅台' : '长江电力';
  const filtered = useMemo(() => catalog.filter(item => (!category || item.category === category) && (!source || item.source === source)
    && `${item.name}${item.source}${item.description}`.includes(query)), [category,source,query]);
  useEffect(()=>setPage(1),[category]);
  let hiddenGroup=false;
  const filteredLines = reports[reportKind].filter(line=>{if(line.group){hiddenGroup=collapsedGroups.includes(line.id);return line.label.includes(find);}return (find||!hiddenGroup)&&line.label.includes(find)&&(showEmpty||line.values.some(v=>v!==null));});
  const factor=(unit==='万元'?10000:unit==='元'?100000000:1)*(security==='000333'?1:security==='600519'?.6:.4);
  const format=(v:number|null)=>v===null?'—':(v*factor).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const selectCategory = (value: string) => { onCategory(value); setPage(1); };
  const catalogColumns: TableColumnsType<CatalogItem> = [
    { title:'数据名称', dataIndex:'name', width:'26%', ellipsis:true, render:(text,r) => <Button type="link" className="table-link" onClick={() => openItem(r)}>{text}</Button> },
    { title:'分类', dataIndex:'category', width:'12%' }, { title:'来源', dataIndex:'source', width:'13%' },
    { title:'用途与范围', dataIndex:'description', ellipsis:{showTitle:false}, render:text => <Tooltip title={text}><span className="muted">{text || '查看数据说明'}</span></Tooltip> },
    { title:'', width:120, render:(_,r) => <Button type="text" onClick={() => openItem(r)}>{['income','balance','cashflow'].includes(r.id)?'打开报表':'浏览数据'}<ArrowRightOutlined /></Button> },
  ];
  const columns: TableColumnsType<StatementRow> = [
    { title:'会计科目', dataIndex:'label', key:'label', width:290, fixed:'left', render:(value,row) => row.group?<Button type="text" size="small" onClick={()=>setCollapsedGroups(old=>old.includes(row.id)?old.filter(id=>id!==row.id):[...old,row.id])}>{collapsedGroups.includes(row.id)?'＋':'－'} {value}</Button>:<span className={row.indent?'line-child':''}>{value}</span> },
    ...periods.flatMap((period,index) => visible.includes(period)?[{
      key:period, width:146, align:'right' as const,
      title:<div className="period-heading"><strong>{period}</strong><span>{periodNames[index]}</span></div>,
      render:(_:unknown,row:StatementRow) => {
        const raw=row.values[index];
        return <button className="financial-cell number" onClick={()=>setCell({label:row.label,period,value:raw})} aria-label={`${row.label} ${period} 数值详情`}>{format(raw)}</button>;
      },
    }]:[]),
  ];
  if(view==='catalog'&&opened)return <Dataset key={opened} id={opened} security={linkedSecurity} onNavigate={(id,code)=>{setOpened(id);setLinkedSecurity(code);}} onBack={()=>setOpened(undefined)} compact={compact}/>;
  return <div className="page-stack">
    <header className="page-heading-v2">
      <div className="heading-title"><span className="page-symbol">{view==='statements'?<Button type="text" aria-label="返回数据目录" title="返回数据目录" icon={<ArrowLeftOutlined />} onClick={onBack} />:<FileTextOutlined />}</span><div><h1>{view==='catalog'?'数据目录':reportNames[reportKind]}</h1><span className="muted">{view==='catalog'?'按业务和来源找到需要的数据':`${securityName} · ${security}.${security.startsWith("6")?"SH":"SZ"} · 同花顺`}</span></div></div>
      <Space><Button icon={<InfoCircleOutlined />} onClick={() => setDetails('statement')}>{view==='catalog'?'目录说明':'报表说明'}</Button>{view==='statements'&&<Button onClick={onTasks}>管理采集<ArrowRightOutlined /></Button>}</Space>
    </header>
    <section className="workspace-surface fill">
      {view==='catalog'?<>
        <div className="query-row"><Input prefix={<SearchOutlined />} aria-label="搜索数据目录" placeholder="搜索数据名称、来源或用途" value={query} onChange={e=>{setQuery(e.target.value);setPage(1);}} allowClear className="search-wide" /><Select aria-label="目录来源" allowClear placeholder="全部来源" value={source} onChange={v=>{setSource(v);setPage(1);}} options={[...new Set(catalog.map(c=>c.source))].map(value=>({value,label:value}))} className="field-medium" /><span className="flex-gap" /><Tools refresh={()=>notify('已刷新目录示例；没有发出网络请求。')} /></div>
        <div className="result-bar"><span><strong>{filtered.length}</strong> 份数据{category&&<Tag closable onClose={()=>selectCategory('')}>{category}</Tag>}</span><span className="muted">按分类与来源浏览</span></div>
        <div className="table-viewport catalog-table" key="catalog" ref={ref}><Table tableLayout="fixed" rowKey="id" columns={catalogColumns} dataSource={filtered.slice((page-1)*30,page*30)} pagination={false} size={compact?'small':'middle'} scroll={{y:height}} locale={{emptyText:<NoResults reset={()=>{setQuery('');setSource(undefined);selectCategory('');}} />}} /></div>
        <div className="table-footer"><span className="muted">选择数据名称打开预览 · 共 {filtered.length} 项</span><Pagination hideOnSinglePage size="small" current={page} pageSize={30} total={filtered.length} onChange={setPage} showSizeChanger={false} showTotal={total=>`共 ${total} 项`} /></div>
      </>:<>
        <div className="query-row financial-query"><label>证券<Select aria-label="选择报表证券" showSearch value={security} onChange={setSecurity} options={[{value:'000333',label:'000333  美的集团'},{value:'600519',label:'600519  贵州茅台'},{value:'600900',label:'600900  长江电力'}]} style={{width:210}} /></label><Segmented aria-label="报表类型" value={reportKind} onChange={v=>{setReportKind(v);setCollapsedGroups([]);setFind('');}} options={Object.entries(reportNames).map(([value,label])=>({value,label}))}/><span className="flex-gap" /><Badge status="default" text={reportKind==='balance'?'期末时点口径':'年初至报告期末累计'} /></div>
        <div className="financial-masthead">{reports[reportKind].filter(r=>r.group).slice(0,3).map(r=><div key={r.id}><small>{r.label}</small><strong>{format(r.values[0])}</strong><em>{unit} · {periods[0]}</em></div>)}</div><div className="report-toolbar"><Input prefix={<SearchOutlined />} value={find} onChange={e=>setFind(e.target.value)} aria-label="查找会计科目" placeholder="查找会计科目" allowClear className="field-large" /><Checkbox checked={showEmpty} onChange={e=>setShowEmpty(e.target.checked)}>显示空值科目</Checkbox><span className="flex-gap" /><label className="inline-label">单位<Select aria-label="报表金额单位" value={unit} onChange={setUnit} options={['亿元','万元','元'].map(value=>({value,label:value}))} style={{width:80}} /></label><Popover trigger="click" title="显示报告期" content={<Checkbox.Group className="period-picker" value={visible} onChange={v=>v.length&&setVisible(v as string[])} options={periods.map(value=>({value,label:value}))} />}><Button icon={<TableOutlined />}>报告期</Button></Popover><Tools refresh={()=>notify('已刷新报表示例；没有查询真实数据库。')} /></div>
        <div className="table-viewport statement-table" key="statement" ref={ref}><Table<StatementRow> rowKey="id" columns={columns} dataSource={filteredLines} pagination={false} size={compact?'small':'middle'} rowClassName={r=>r.group?'statement-total':''} scroll={{x:290+visible.length*146,y:height}} locale={{emptyText:<NoResults reset={()=>setFind('')} />}} /></div>
        <div className="table-footer"><span><strong>{filteredLines.length}</strong> 个科目 · <strong>{visible.length}</strong> 个报告期<span className="footer-divider" />金额：{unit} · “—”表示未提供</span><span className="muted">所有财务数值均为虚构示例</span></div>
      </>}
    </section>
    <Drawer open={!!cell} onClose={()=>setCell(undefined)} title="科目与数值口径" size={440}>{cell&&<div className="drawer-copy"><Tag>{reportNames[reportKind]}</Tag><h3>{cell.label}</h3><p>报告期：{cell.period}</p><h2>{format(cell.value)} {cell.value===null?'':unit}</h2><p>{cell.value===null?'来源未提供，不视为零。':reportKind==='balance'?'这是报告期末的时点余额。':'这是年初至报告期末的累计数，不是单季度数。'}</p><p>公告与历史可用日期：未提供。</p><p className="muted">虚构数值，仅用于设计评审。</p></div>}</Drawer>
    <Drawer open={!!details} onClose={()=>setDetails(undefined)} title={details==='statement'?(view==='catalog'?'目录说明':'报表口径与来源'):details?.name} size={440}>
      {details==='statement'?<div className="drawer-copy"><Tag color="blue">设计评审</Tag><h3>{view==='catalog'?'从目录进入业务页面':`${reportNames[reportKind]} · ${reportKind==='balance'?'期末时点':'累计报告'}口径`}</h3><p>报表采用“科目 × 报告期”矩阵；资产负债表为期末时点，利润表和现金流量表为累计口径。累计值不直接当作单季度值比较。</p><h4>日期与可用性</h4><p>当前示例未提供公告日期和历史可用日期，不能用于历史公告前选股。空值保留为“—”，不填成 0。</p><h4>当前预览范围</h4><p>全部50项数据目录均有可交互的数据样本预览；各项按业务类型呈现，不连接真实数据库。目录来自现有 50 项页面登记；本预览不连接业务数据库。</p></div>:details&&<div className="drawer-copy"><Space><Tag>{details.category}</Tag><Tag>{details.source}</Tag></Space><h3>{details.name}</h3><p>{details.description}</p><p className="muted">该业务已登记在现有客户端，本版先展示其目录位置与说明；对应详细页面尚未纳入本次设计评审。</p></div>}
    </Drawer>
  </div>;
}