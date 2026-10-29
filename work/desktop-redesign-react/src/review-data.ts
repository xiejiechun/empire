import inventory from '../route-inventory.json';

// Deliberately invented, bounded design fixtures. No real business connections.
export type Screen = 'catalog' | 'statements' | 'tasks' | 'archived' | 'platforms' | 'resources' | 'identities';
export type RunState = '采集中' | '等待归档' | '请求失败' | '来源缺口' | '已核验' | '已暂停';
export type Task = { id: string; name: string; source: string; category: string; state: RunState; done: number; total: number; queued: number; pending: number; written: number; updated: string; next: string };
export const taskSeeds: [string, string, string, string, RunState][] = [
  ['income','利润表','同花顺','公司财务','请求失败'],
  ['daily','股票历史日行情','同花顺','交易与行情','采集中'],
  ['news','财经快讯','新浪财经','新闻资讯','等待归档'],
  ['balance','资产负债表','同花顺','公司财务','已核验'],
  ['cashflow','现金流量表','同花顺','公司财务','已核验'],
  ['stocks','股票列表','新浪财经','证券基础','已核验'],
  ['calendar','A 股交易日历','巨潮资讯','交易与行情','已核验'],
  ['holders','前十大股东','同花顺','股东研究','来源缺口'],
  ['float','前十大流通股东（同一股东任务）','同花顺','股东研究','采集中'],
  ['counts','股东户数','通达信','股东研究','已核验'],
  ['dividends','分红送转','通达信','公司事件','已核验'],
  ['issues','增发','通达信','公司事件','已核验'],
  ['rights','配股','通达信','公司事件','已暂停'],
  ['suspensions','历史停复牌','通达信','交易与行情','已核验'],
  ['indices','当前指数及成分','同花顺','指数行业','已核验'],
  ['industries','当前行业及成分','同花顺','指数行业','已核验'],
  ['index-prices','指数历史日行情','同花顺','指数行业','采集中'],
  ['repurchases','股票回购','东方财富','公司事件','已核验'],
  ['unlocks','限售股解禁明细','通达信','股东研究','已暂停'],
  ['themes','题材库','开盘啦','题材研究','已核验'],
  ['limits','涨停池','同花顺','交易与行情','已核验'],
  ['disclosures','财报披露时间','通达信','公司财务','已核验'],
  ['forecast','业绩预告','通达信','公司财务','已核验'],
  ['names','公司更名','通达信','证券基础','已暂停'],
];
export const tasks: Task[] = taskSeeds.map(([id,name,source,category,state], i) => ({
  id,name,source,category,state,
  done: state === '等待归档' ? 360 : state === '请求失败' ? 18 : state === '来源缺口' ? 28 : state === '采集中' ? 92 + i * 13 : state === '已暂停' ? 0 : 30,
  total: ['请求失败','来源缺口','已核验'].includes(state) ? (state === '请求失败' ? 20 : 30) : 360,
  queued: state === '已暂停' ? 0 : 120 + i * 8,
  pending: state === '等待归档' ? 20 : state === '采集中' ? 8 : 0,
  written: state === '已暂停' || i % 3 === 0 ? 0 : 12 + i,
  updated: `10-28 ${String(17 - i % 3).padStart(2,'0')}:${String(42 - i).padStart(2,'0')}:12`,
  next: state === '已暂停' ? '未安排' : state === '采集中' ? '本轮结束后 1 小时' : '10-29 18:30',
}));

export const catalog = Object.values(inventory.pages).filter(p => p.catalogued).map(p => ({
  id: p.id, name: p.title, category: p.category, source: p.source || '内部计算', description: p.description,
}));
export const periods = ['2026-06-30','2026-03-31','2025-12-31','2025-09-30','2025-06-30','2025-03-31'];
export const periodNames = ['中报','一季报','年报','三季报','中报','一季报'];
export type StatementRow = { id: string; label: string; group?: boolean; indent?: boolean; values: (number | null)[] };
const lineSeeds: [string, number | null, ('group' | 'child')?][] = [
  ['一、营业总收入',2521.5,'group'],['其中：营业收入',2521.5,'child'],
  ['二、营业总成本',2306.2,'group'],['营业成本',1857.2,'child'],['税金及附加',16.4,'child'],
  ['销售费用',172.5,'child'],['管理费用',82.3,'child'],['研发费用',88.6,'child'],['财务费用',-10.8,'child'],
  ['其中：利息费用',8.9,'child'],['其中：利息收入',22.7,'child'],
  ['加：其他收益',25.4],['投资收益',12.3],['其中：联营及合营企业投资收益',4.6,'child'],
  ['公允价值变动收益',2.8],['信用减值损失',-3.1],['资产减值损失',-8.4],['资产处置收益',1.2],
  ['三、营业利润',245.5,'group'],['加：营业外收入',3.5,'child'],['减：营业外支出',1.6,'child'],
  ['四、利润总额',247.4,'group'],['减：所得税费用',42.3,'child'],
  ['五、净利润',205.1,'group'],['持续经营净利润',205.1,'child'],['终止经营净利润',null,'child'],
  ['归属于母公司股东的净利润',195.9,'child'],['少数股东损益',9.2,'child'],
  ['六、其他综合收益税后净额',-2.3,'group'],['七、综合收益总额',202.8,'group'],
  ['归属于母公司股东的综合收益',193.7,'child'],['归属于少数股东的综合收益',9.1,'child'],
];
export const statement: StatementRow[] = lineSeeds.map(([label, value, kind], i) => ({
  id: String(i), label, group: kind === 'group', indent: kind === 'child',
  values: [1, .46, 1.84, 1.31, .92, .42].map(ratio => value === null ? null : Math.round(value * ratio * 100) / 100),
}));
export type Plan = { enabled: boolean; mode: 'daily' | 'interval' | 'manual'; time: string; interval: number; network: 'proxy_fallback' | 'proxy_only' | 'direct'; retries: number };
export const defaultPlan: Plan = { enabled: true, mode: 'daily', time: '18:30', interval: 3600, network: 'proxy_fallback', retries: 2 };
export const planText = (p: Plan) => !p.enabled ? '计划已停用' : p.mode === 'daily' ? `每天 ${p.time} · 北京时间` : p.mode === 'interval' ? `每轮结束后等待 ${p.interval.toLocaleString()} 秒` : '仅手动执行';
