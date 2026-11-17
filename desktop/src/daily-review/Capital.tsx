import { Alert, Tag } from 'antd';
import { Detail } from './ReviewSections';
import { signed } from './report';
import type { CapitalStock, EtfEstimate, MarketData, SectorRow } from './useMarket';

const missing = <span className="review-missing">缺少数据来源</span>;
function Amount({ value }: { value: number | string | null | undefined }) {
  if (value == null) return missing;
  const amount = Number(value);
  return <span className={amount > 0 ? 'review-up' : amount < 0 ? 'review-down' : ''} title={`${value}元`}>{signed(amount / 100000000)}亿</span>;
}
function Ranking({ items, inflow }: { items: CapitalStock[] | null | undefined; inflow: boolean }) {
  return <div><h3>个股净{inflow ? '流入' : '流出'} Top 5</h3>{items == null ? missing : items.length === 0 ? <span className="review-muted">当日无净{inflow ? '流入' : '流出'}个股</span> : items.map((item, index) => <div className="review-rank" key={item.unified_code}>
    <span>{index + 1}</span><span>{item.name}<small>{item.unified_code} · 涨幅 {item.change_ratio == null ? missing : `${signed(Number(item.change_ratio) * 100)}%`}</small></span><b><Amount value={item.amount_yuan} /></b>
  </div>)}</div>;
}

function EtfValue({ title, value }: { title: string; value?: EtfEstimate | null }) {
  return <span>{title} <Amount value={value?.amount_yuan} />{value && <small className="review-muted"> · 有效覆盖 {value.covered_count}/{value.target_count}{value.covered_count > 0 && value.covered_count < value.target_count ? '（部分样本合计）' : ''}</small>}</span>;
}

function SectorRanking({ items, inflow }: { items: SectorRow[] | null | undefined; inflow: boolean }) {
  return <div><h3>板块主力{inflow ? '流入' : '流出'} Top 5</h3>{items == null ? missing : items.length === 0 ? <span className="review-muted">无净{inflow ? '流入' : '流出'}板块（已覆盖样本）</span> : items.map((item, index) => <div className="review-sector-rank" key={item.industry_code}>
    <span>{index + 1}</span><span>{item.name}<small>覆盖{item.covered_count}/{item.member_count}只 · {item.covered_count === item.member_count ? '覆盖完整' : <span className="review-sector-partial">部分覆盖</span>}</small></span><b><Amount value={item.amount_yuan} /></b>
  </div>)}</div>;
}

export default function Capital({ data, loading, error }: { data?: MarketData; loading: boolean; error: string }) {
  const sectors = data?.capital?.sectors;
  return <div aria-busy={loading}>
    <div className="review-market-status"><Tag color="blue">真实归档 · 个股资金</Tag><span>{loading ? '正在读取所选日期…' : data?.main_flow_yuan != null ? `东方财富模型测算 · ${data.fund_count}只` : '缺少数据来源'}</span></div>
    {error && <Alert type="error" showIcon title={data ? '资金刷新失败，保留上次读取的同日数据' : '资金流向读取失败，请重试'} description={error} />}
    <div className="review-capital-stats">
      <div><small>主力净流入 · 含暗盘</small><strong><Amount value={data?.main_flow_yuan} /></strong></div>
      <div><small>明盘资金合计</small><strong><Amount value={data?.capital?.visible_flow_yuan} /></strong></div>
      <div><small>暗盘资金合计</small><strong><Amount value={data?.capital?.dark_flow_yuan} /></strong></div>
    </div>
    <div className="review-capital-sectors">
      <div className="review-sector-basis"><Tag color="blue">自行汇总</Tag><span>按当前成分股回看</span><small>按已覆盖成分股合计排名</small></div>
      {sectors?.issue && <p className="review-muted">板块资金暂不可用：{sectors.issue}</p>}
      <div className="review-grid-two"><SectorRanking items={sectors?.inflow} inflow /><SectorRanking items={sectors?.outflow} inflow={false} /></div>
    </div>
    <div className="review-etf"><strong>ETF净申赎估算</strong><EtfValue title="本日" value={data?.capital?.etf?.current} /><EtfValue title={`前一交易日${data?.previous_date ? `（${data.previous_date}）` : ''}`} value={data?.capital?.etf?.previous} /></div>
    <Detail title="ETF数据覆盖与缺项">
      <p className="review-muted">{data?.capital?.etf?.basis || '按当前ETF目录回看'}。估算为连续两日总份额之差，扣除已证实的非申赎变动，再乘当日单位净值；不等同现金到账额。收益值不作为单位净值。</p>
      {data?.capital?.etf?.issue && <p className="review-muted">{data.capital.etf.issue}</p>}
      {(['current', 'previous'] as const).map(key => { const item = data?.capital?.etf?.[key]; return item && <p className="review-muted" key={key}>{key === 'current' ? '本日' : '前一交易日'}：两日份额和单位净值已具备 {item.candidate_count}/{item.target_count} 只；缺份额 {item.missing.missing_shares}、缺净值 {item.missing.missing_nav}、收益口径 {item.missing.income_only}、币种未核实 {item.missing.unknown_currency}、非申赎变动待核实 {item.missing.event_review}。后两项可能重叠。</p>; })}
      <p className="review-muted">缺少币种或折算等事件依据的ETF暂不计入金额；缺失不填0，未收盘、休市不套用上日值。</p>
    </Detail>
    <Detail title="个股资金排行与口径">
      <div className="review-grid-two"><Ranking items={data?.capital?.inflow} inflow /><Ranking items={data?.capital?.outflow} inflow={false} /></div>
      <p className="review-muted">按所选日完整资金榜的含暗盘主力净流入排序，同金额按证券代码排序；榜单仅含正值或负值，最多各5只。明盘加暗盘等于含暗盘主力净流入，均为来源模型测算，不是实际暗盘成交。个股资金不等于板块资金或ETF净申赎。</p>
      <p className="review-muted">板块使用同花顺当前行业成分股，合计所选日已覆盖个股的含暗盘主力净流入；部分覆盖不是全板块金额，缺失个股不按0计入，零覆盖不入榜。历史日期按当前成分股回看，成分更新后结果可能改变，不代表当日历史行业归属。</p>
      {sectors?.basis_observed_at && <p className="review-muted">当前成分最近归档核验：{new Date(sectors.basis_observed_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}。{sectors.industry_count}个行业：完整覆盖{sectors.complete_count}个、部分覆盖{sectors.partial_count}个、无覆盖{sectors.uncovered_count}个。</p>}
      <p className="review-muted">{data ? `查询于 ${new Date(data.queried_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}。` : ''}休市、未收盘或未归档不套用上日数据。</p>
    </Detail>
  </div>;
}
