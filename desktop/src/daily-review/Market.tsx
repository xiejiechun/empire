import { Alert, Tag } from 'antd';
import { Detail } from './ReviewSections';
import { number, signed } from './report';
import type { MarketData } from './useMarket';

const missing = <span className="review-missing">缺少数据来源</span>;
function Change({ value, money = false }: { value: number | string | null | undefined; money?: boolean }) {
  if (value == null) return missing;
  const amount = Number(value) / (money ? 100000000 : 1);
  return <span className={amount > 0 ? 'review-up' : amount < 0 ? 'review-down' : ''} title={String(value)}>{signed(amount)}{money ? '亿' : '%'}</span>;
}
const states = { closed: '所选日已收盘', rest: '当日休市', pending: '收盘前，日终数据尚未就绪', future: '所选日期尚未到来', unknown: '缺少正式交易日历' };

export default function Market({ data, loading, error }: { data?: MarketData; loading: boolean; error: string }) {
  return <>
    <div className="review-market-status"><Tag color="blue">真实数据</Tag><span>{loading ? '正在读取所选日期…' : error ? '读取失败' : data && states[data.status]}</span>{data && <small>查询于 {new Date(data.queried_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</small>}</div>
    {error && <Alert type="error" showIcon title={data ? '刷新失败，保留上次读取的同日数据' : '整体行情读取失败，请重试'} description={error} />}
    {data?.issues.map(issue => <Alert key={issue} type="warning" title={issue} />)}
    <div className="review-stats" aria-busy={loading}>
      <div><small>涨停 / 跌停</small><strong><span className="review-up">{data?.limit_up ?? missing}</span> / {data?.limit_down ?? missing}</strong><span>{data?.first_boards == null ? missing : `${data.first_boards}首板`} · {data?.chain == null ? missing : `${data.chain}连板`}</span></div>
      <div><small>成交额 · 归档个股合计</small><strong title={data?.amount_yuan == null ? undefined : `${data.amount_yuan}元`}>{data?.amount_yuan == null ? missing : <>{number(Number(data.amount_yuan) / 1000000000000)}<small>万亿</small></>}</strong><span>较前交易日 <Change value={data?.amount_change_yuan} money /></span><small>当日{data?.price_count ?? 0}只 / 前日{data?.previous_price_count ?? 0}只</small></div>
      <div><small>主力资金 · 含暗盘</small><strong><Change value={data?.main_flow_yuan} money /></strong><span>东方财富模型测算 · {data?.fund_count ?? 0}只</span></div>
      <div><small>上涨 / 下跌 · 资金榜样本</small><strong>{data?.advance == null ? missing : number(data.advance)} / {data?.decline == null ? missing : number(data.decline)}</strong><span>平盘 {data?.flat == null ? missing : `${number(data.flat)}家`}</span></div>
    </div>
    <div className="review-indices">{(data?.indices ?? ['上证指数', '深证成指', '科创50', '创业板指', '沪深300', '北证50'].map(name => ({ name, change: null }))).map(i => <div key={i.name}><span>{i.name}</span><Change value={i.change} /></div>)}</div>
    <Detail title="指数点位与数据口径">
      <div className="review-table-scroll"><table aria-label="真实指数收盘点位"><thead><tr><th>指数</th><th className="review-num">收盘点位</th><th className="review-num">涨跌幅</th></tr></thead><tbody>{data?.indices.map(i => <tr key={i.name}><td>{i.name}</td><td className="review-num">{i.close == null ? missing : number(Number(i.close))}</td><td className="review-num"><Change value={i.change} /></td></tr>)}</tbody></table></div>
      <h3 className="review-subheading">外围市场</h3>
      <div className="review-overseas">{(data?.overseas ?? ['日经225', '韩国综合', '纳斯达克', 'SOX', '微软'].map(name => ({ name, change: null }))).map(i => <div key={i.name}><span>{i.name}</span><Change value={i.change} /></div>)}</div>
      <p className="review-muted">成交额为已归档沪深京个股合计，未归档证券不计入；两日样本数可能不同。资金和涨跌家数仅代表东方财富资金榜样本，资金为含暗盘模型测算。涨跌停按远航来源池范围；连板按正式交易日连续涨停计算。指数涨幅只与前一交易日同代码收盘比较。</p>
      <p className="review-muted">前一交易日：{data?.previous_date ?? '缺少数据来源'}。休市、未收盘、未归档或尚无来源的字段统一保留缺值；刷新只读取已有归档。</p>
    </Detail>
  </>;
}
