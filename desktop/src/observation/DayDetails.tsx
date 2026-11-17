import { Button, Drawer, Empty, Tag } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { formatValue, liveDescription, observationName, metricColor, type Day, type Metric } from './model';

export default function DayDetails({ day, metrics, indexName, marketName, onClose, previousDate, nextDate, onNavigate }: {
  day?: Day; metrics: Metric[]; indexName: string; marketName: string; onClose: () => void;
  previousDate?: string; nextDate?: string; onNavigate: (date: string) => void;
}) {
  return <Drawer title={day ? `${day.date} · 观察详情` : '观察详情'} open={!!day} onClose={onClose} size="min(480px,95vw)">
    {day && <div className="observation-details">
      <div className="detail-navigation"><Button icon={<LeftOutlined />} disabled={!previousDate} onClick={() => previousDate && onNavigate(previousDate)}>前一天</Button><span>{day.date}</span><Button icon={<RightOutlined />} disabled={!nextDate} onClick={() => nextDate && onNavigate(nextDate)}>后一天</Button></div>
      <div className="detail-context"><Tag color={day.status === 'trade' ? 'blue' : undefined}>{day.status === 'trade' ? 'A股交易日' : day.status === 'closed' ? 'A股休市' : 'A股日历未确认'}</Tag>{day.future && <Tag>未来日期</Tag>}</div>
      <h2>{indexName}</h2><p className="muted">两融范围：{marketName} · 金额及比例保留精确原值</p>
      {day.status !== 'trade' || day.future ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={day.future ? '尚未到达该日期' : day.status === 'closed' ? '正式日历确认A股休市，汇率按自身来源日期展示' : 'A股日历覆盖待核查，汇率按自身来源日期展示'} /> : null}
      {!day.future && <>
        {day.status === 'trade' && <div className="detail-return"><span>指数涨跌幅</span><strong className={Number(('index_daily_change' in day.values ? day.values.index_daily_change : day.values.change)) > 0 ? 'rise' : Number(('index_daily_change' in day.values ? day.values.index_daily_change : day.values.change)) < 0 ? 'fall' : ''}>{formatValue(('index_daily_change' in day.values ? day.values.index_daily_change : day.values.change), '%')}</strong></div>}
        {!metrics.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未选择观察指标" />}
        {metrics.filter(metric => day.status === 'trade' || metric.scope === 'fx').map(metric => <div className="detail-metric" key={metric.key}>
          <div><i style={{ background: metricColor(metric.key) }} /><b>{observationName(metric, day.sources?.[metric.key])}</b>{day.sources?.[metric.key] && <Tag color={day.sources[metric.key].sampling_stale ? 'orange' : 'cyan'}>Redis · {day.sources[metric.key].sampling_stale ? '采样过期' : '盘中'}</Tag>}<small>{day.sources?.[metric.key] ? liveDescription(day.sources[metric.key]) : metric.description || (metric.scope === 'index' ? indexName : marketName)}</small></div>
          <strong>{day.values[metric.key] ?? '未取得可用值'}</strong><span className="muted">{metric.unit}</span>
        </div>)}
        {day.status === 'trade' && metrics.some(m => m.key === 'financing_repayment_ratio') && <div className="detail-ratio-basis"><b>融资买入/偿还比 · 当日原始口径</b><p>买入额：{day.values.financing_ratio_buy ?? '缺值'} 元</p><p>偿还额（买入额 − 净买入额）：{day.values.financing_ratio_repayment ?? '缺值'} 元</p><p>买入额 ÷ 偿还额 × 100%；缺值或偿还额非正时不计算。月历的均值、环比在该原始比值上计算。</p></div>}
      </>}
      <p className="detail-footnote">缺值不代表零。详情与月历同步更新今日Redis盘中值；更新归档数据请点击“刷新数据”。</p>
    </div>}
  </Drawer>;
}
