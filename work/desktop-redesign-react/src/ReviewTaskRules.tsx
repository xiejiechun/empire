import {Alert,Collapse,Descriptions,Table,Tag} from 'antd';
import rules from './collection-rules.json';
import type {Task} from './review-data';
const mapping:Record<string,string>={income:'ths-income',balance:'ths-balance',cashflow:'ths-cashflow',daily:'ths-yuanhang-prices',news:'sina-news',stocks:'sina-stocks',calendar:'cninfo-calendar',holders:'ths-holders',float:'ths-holders',counts:'tdx-holder-count',dividends:'tdx-dividends',issues:'tdx-additional-issues',rights:'tdx-rights-issues',suspensions:'tdx-suspensions',indices:'ths-indices',industries:'ths-industries','index-prices':'ths-index-prices',repurchases:'eastmoney-repurchases',unlocks:'tdx-unlocks',themes:'kaipanla-themes',limits:'ths-yuanhang-limit-up-pool',disclosures:'tdx-earnings-disclosure',forecast:'tdx-earnings-forecast',names:'tdx-company-renames'};
export const ruleId=(id:string)=>mapping[id]||id;
export const ruleFor=(id:string)=>(rules.tasks as Record<string,typeof rules.tasks['ths-income']>)[ruleId(id)];
export default function TaskRules({task}:{task:Task}){
 const r=ruleFor(task.id);
 if(!r)return <Alert type="warning" title="该任务尚未映射来源说明，不使用通用说明代替来源契约。"/>;
 const fields=[['scope','证券与市场'],['start','开始范围'],['end','结束范围'],['initial','首次初始化'],['incremental','日常维护与修订'],['fresh','重新采集'],['recovery','中断与状态丢失恢复'],['limits','用途限制']] as const;
 return <div className="rule-copy"><Alert type="info" showIcon title="现有客户端采集契约 · 离线快照 2026-10-29" description="说明来自项目静态规则文件；进度和运行结果仍为演示数据。"/><p><Tag>{ruleId(task.id)}</Tag><span className="muted">{r.job_key}</span></p><Descriptions column={1} size="small" bordered items={fields.map(([key,label])=>({key,label,children:r[key]}))}/><Collapse style={{marginTop:16}} items={[{key:'requests',label:'来源请求与参数',children:r.requests.map((q,i)=><div key={i}><h4>{q.purpose} · {q.method}</h4><p style={{overflowWrap:'anywhere'}}>{q.url}</p><Table size="small" pagination={false} rowKey="name" dataSource={q.parameters} columns={[{title:'参数',dataIndex:'name'},{title:'值',dataIndex:'value'},{title:'用途',dataIndex:'meaning'}]}/></div>)},{key:'storage',label:'数据去向与配置生效',children:<><p>数据集：{r.datasets.join('、')}<br/>业务表：{r.tables.join('、')||'无业务表'}</p><p>执行安排保存后生效；网络与重试从下一轮生效。共享下载资源保存后须正常重启。</p><p>实现参考：{r.source_file}</p><p>相关说明：{r.topics.join('、')}</p></>}]} /></div>;
}
