import {Button,Space,Tag} from 'antd';
import {ArrowLeftOutlined} from '@ant-design/icons';
import {catalog} from './review-data';
import {StockBrowser,NewsReader,CalendarBrowser} from './ReviewReadingViews';
import PriceExplorer from './ReviewPriceExplorer';
import AllDatasetPreview,{allDefinitions} from './ReviewAllDatasets';
import './review-datasets.css';
export default function Dataset({id,onBack,compact,onNavigate,security}:{id:string;onBack:()=>void;compact:boolean;onNavigate:(id:string,code?:string)=>void;security?:string}){
 const item=catalog.find(c=>c.id===id)!;
 const notes:Record<string,string>={stocks:'证券目录与档案 · 选择证券后查看资料或历史行情',news:'按发布时间阅读 · 列表与正文保持同屏',calendar:'交易安排与覆盖状态 · 缺失日期不视为休市',yuanhang:'历史量价 · 走势图与逐日记录联动'};
 return <div className="page-stack bespoke-page"><header className="page-heading-v2"><div className="heading-title"><Button aria-label="返回数据目录" icon={<ArrowLeftOutlined/>} onClick={onBack}/><div><h1>{item.name}</h1><span className="muted">{notes[id]||item.description}</span></div></div><Space><span className="muted">{item.source}</span><Tag>设计样本</Tag></Space></header>{id==='stocks'?<StockBrowser compact={compact} onPrice={code=>onNavigate('yuanhang',code)}/>:id==='news'?<NewsReader/>:id==='calendar'?<CalendarBrowser/>:id==='yuanhang'?<PriceExplorer initialSecurity={security}/>:<AllDatasetPreview id={id}/>}</div>;
}
