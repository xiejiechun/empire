import { Tooltip } from 'antd';
import { chinaToday, formatValue, liveDescription, observationName, metricColor, type Day, type Metric } from './model';

export default function MonthGrid({ rows, month, metrics, indexName, marketName, thresholds, highlight,
  focusedMetric, selectedDate, onOpen }: {
  rows: Day[]; month: string; metrics: Metric[]; indexName: string; marketName: string;
  thresholds: Record<string, number>; highlight: boolean; focusedMetric: string | null;
  selectedDate?: string; onOpen: (date: string) => void;
}) {
  const today = chinaToday();
  return <div className={`observation-grid ${focusedMetric ? 'tracking-metric' : ''}`} role="table" aria-label={`${month}观察月历`}>
    {['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((day, i) => <div className={`observation-weekday ${i > 4 ? 'weekend-heading' : ''}`} key={day} role="columnheader">{day}</div>)}
    {rows.map(day => {
      const change = 'index_daily_change' in day.values ? day.values.index_daily_change : day.values.change;
      const direction = change != null && Number(change) > 0 ? 'rise' : change != null && Number(change) < 0 ? 'fall' : '';
      return <div role="cell" key={day.date} data-date={day.date} className={`observation-day ${day.in_month ? '' : 'outside-month'} ${day.date === today ? 'is-today' : ''} ${selectedDate === day.date ? 'selected-day' : ''} status-${day.status}`}>
        <div className="day-heading">
          <div className="observation-date"><button className="day-detail-trigger" aria-label={`查看${day.date}详情`} onClick={() => onOpen(day.date)}><time dateTime={day.date}>{!day.in_month && <small>{Number(day.date.slice(5, 7))}月 </small>}{Number(day.date.slice(-2))}</time></button>{day.date === today && <small>今天</small>}{day.future && <small>未来</small>}</div>
          {day.status === 'trade' && !day.future && <Tooltip title={`${indexName} · 当日涨跌幅`}><span className={`day-return ${direction}`}>{change != null && Number(change) > 0 ? '+' : ''}{formatValue(change, '%')}</span></Tooltip>}
        </div>
        {day.status !== 'trade' && <div className="day-empty">{day.status === 'closed' ? 'A股休市' : 'A股日历未确认'}</div>}
        {day.future ? <div className="day-empty future-empty">待到日期</div> : <div className="day-values">
          {!metrics.length && <div className="day-empty">尚未选择指标</div>}
          {metrics.filter(metric => day.status === 'trade' || metric.scope === 'fx').map(metric => {
            const value = day.values[metric.key], threshold = thresholds[metric.key];
            const source = day.sources?.[metric.key], name = observationName(metric, source);
            const high = highlight && value != null && threshold != null && Number(value) >= threshold;
            return <Tooltip key={metric.key} title={`${name}：${value ?? '未取得可用值'} ${value == null ? '' : metric.unit} · ${source ? liveDescription(source) : metric.description || (metric.scope === 'index' ? indexName : marketName)}${high ? ' · 达到高亮阈值' : ''}`}>
              <div data-metric={metric.key} className={`day-metric ${high ? 'metric-highlight' : ''} ${focusedMetric === metric.key ? 'metric-tracked' : ''} ${focusedMetric && focusedMetric !== metric.key ? 'metric-dimmed' : ''}`}>
                <span><i style={{ background: metricColor(metric.key) }} />{name}</span><b>{formatValue(value, metric.unit)}</b>
              </div>
            </Tooltip>;
          })}
        </div>}
      </div>;
    })}
  </div>;
}
