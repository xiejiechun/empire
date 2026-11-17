export type Metric = { key: string; name: string; category: string; unit: string; scope: string; description?: string };
export type LiveSource = { source: 'redis'; latest: string | number; mode: 'value' | 'change' | 'sum'; days: number;
  source_time: string; source_update_time: string; observed_at: string; sampling_stale: boolean };
export type LiveBasis = { mode: 'value' | 'change' | 'sum'; days: number; ready: boolean; total: string };
export type Day = { date: string; in_month: boolean; status: string; future: boolean; values: Record<string, string | number | null>; sources?: Record<string, LiveSource>; live_basis?: Record<string, LiveBasis> };
export type MonthResult = { month: string; index: string; market: string; rows: Day[]; queried_at: string; warnings?: string[] };
export type MetricOption = { market?: string; mode: 'value' | 'change' | 'sum'; days: number; window: number; top: number };
export const defaultOption: MetricOption = { mode: 'value', days: 5, window: 30, top: 5 };
export type View = { index: string; market: string; selected: string[]; density: string; highlight: boolean; thresholds: Record<string, number>; settings: Record<string, MetricOption> };
export const defaultView: View = { index: '', market: '99', selected: ['amount', 'market_amount', 'financing_balance', 'financing_repayment_ratio', 'top_amount_share', 'fx_USDCNH'], density: '标准', highlight: true, thresholds: {}, settings: {} };
const fxKeys = ['USDIND', 'USDCNY', 'USDCNH', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDCAD', 'USDCHF', 'USDHKD', 'AUDUSD', 'USDJPY', 'USDSGD'].map(code => `fx_${code}`);
const metricColors: Record<string, string> = {
  market_amount: '#168e89',
  top_amount_share: '#7c3aed', financing_repayment_ratio: '#dc8b38', close: '#3478f6', change: '#e05b72', amount: '#4782da', volume: '#31a89d',
  financing_balance: '#cf5674', financing_buy: '#bd8730', financing_net_buy: '#dc8b38',
  lending_balance: '#8166c2', lending_net_sell: '#a56ca6', total_balance: '#258e88', balance_ratio: '#6874cc',
  ...Object.fromEntries(fxKeys.map((key, i) => [key, ['#168e89', '#4b80c1', '#ac7735', '#9863b4'][i % 4]])),
};
export const metricColor = (key: string) => metricColors[key] || '#74849b';
const storageKey = 'empire.observation.view.v1';
export function loadView(): View {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || 'null');
    if (value && typeof value.index === 'string' && ['99', '3', '2', '4'].includes(value.market)
      && Array.isArray(value.selected) && value.selected.every((k: unknown) => typeof k === 'string')
      && ['紧凑', '标准', '详细'].includes(value.density) && typeof value.highlight === 'boolean'
      && value.thresholds && typeof value.thresholds === 'object') {
      const selected = [...new Set<string>(value.selected)].filter(k => k in metricColors);
      if (value.schema_version !== 2 && !selected.includes('market_amount')) selected.splice(Math.max(0, selected.indexOf('amount') + 1), 0, 'market_amount');
      return { ...value, settings: cleanSettings(value.settings), selected: selected.slice(0, 26),
        thresholds: Object.fromEntries(Object.entries(value.thresholds).filter(([, v]) => typeof v === 'number' && Number.isFinite(v))) };
    }
  } catch { /* Corrupt preferences never prevent opening the calendar. */ }
  return { ...defaultView };
}
export function saveView(view: View) { localStorage.setItem(storageKey, JSON.stringify({ ...view, schema_version: 2 })); }
export function chinaToday() {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
}
export function shiftMonth(month: string, offset: number) {
  const [year, value] = month.split('-').map(Number);
  return new Date(Date.UTC(year, value - 1 + offset, 1)).toISOString().slice(0, 7);
}
export function formatValue(value: string | number | null | undefined, unit: string) {
  if (value == null) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (unit === '%') return number.toFixed(2) + '%';
  if (['元', '来源口径'].includes(unit) && Math.abs(number) >= 1e8) return (number / 1e8).toFixed(2) + '亿';
  if (['元', '来源口径'].includes(unit) && Math.abs(number) >= 1e4) return (number / 1e4).toFixed(2) + '万';
  return number.toLocaleString('zh-CN', { maximumFractionDigits: ['点', '来源口径', '元'].includes(unit) ? 2 : 6 });
}
export function observationName(metric: Metric, source?: LiveSource) {
  return source ? metric.name.replace('收盘', source.mode === 'value' ? '盘中' : '') : metric.name;
}
export function sourceTime(value: string) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value));
}
export function liveDescription(source: LiveSource) {
  const basis = source.mode === 'value' ? '盘中最新报价，非收盘价' : source.mode === 'change'
    ? '盘中估算：最新报价相对前条归档收盘的变化' : `盘中估算：最新报价与前${source.days - 1}条归档收盘的${source.days}期均值`;
  return `Redis · ${basis} · 最新价 ${source.latest} · 来源时间 ${sourceTime(source.source_time)} · 来源更新时间 ${sourceTime(source.source_update_time)} · 采样 ${sourceTime(source.observed_at)}（北京时间，来源时间不等于成交时刻） · ${source.sampling_stale ? '采样已过期（超过180秒）' : '采样未过期'}；统计基准不足或异常时留空`;
}
export function exportCsv(rows: Day[], metrics: Metric[], index: string, market: string, month: string) {
  const cell = (v: unknown) => '"' + String(v ?? '').replaceAll('"', '""') + '"';
  const lines = [['日期', '日历状态', '未来日期', '指数代码', '两融市场', ...metrics.flatMap(m => [`${m.name}（${m.unit}）${m.description ? ` [${m.description}]` : ''}`, `${m.name}·数据来源`, `${m.name}·来源时间`, `${m.name}·来源更新时间`, `${m.name}·采样时间`, `${m.name}·采样状态`, `${m.name}·盘中原价`])],
    ...rows.filter(r => r.in_month).map(r => [r.date, { trade: 'A股交易日', closed: 'A股休市', unknown: 'A股日历未确认' }[r.status],
      r.future ? '是' : '否', index, market, ...metrics.flatMap(m => {
        const source = r.sources?.[m.key];
        return [r.values[m.key], source ? liveDescription(source) : r.values[m.key] != null ? 'MySQL已归档' : '',
          source?.source_time, source?.source_update_time, source?.observed_at, source ? source.sampling_stale ? '过期' : '未过期' : '', source?.latest];
      })])];
  const url = URL.createObjectURL(new Blob(['\ufeff' + lines.map(r => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = `多指标观察日历-${month}.csv`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function cleanSettings(value: unknown): Record<string, MetricOption> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).slice(0, 26).filter(([, v]) => v && typeof v === 'object'
    && ['value', 'change', 'sum'].includes(v.mode) && Number.isInteger(v.days) && v.days >= 1 && v.days <= 60
    && Number.isInteger(v.window) && v.window >= 1 && v.window <= 60 && Number.isInteger(v.top) && v.top >= 1 && v.top <= 100
    && (v.market == null || ['99', '3', '2', '4'].includes(v.market))).filter(([key]) => key in metricColors)
    .map(([key, v]) => [key, {mode:v.mode, days:v.days, window:v.window, top:v.top, ...(v.market ? {market:v.market} : {})}]));
}
export function configuredMetric(metric: Metric, settings: View['settings'], markets: {code:string;name:string}[], market: string): Metric {
  const option = settings[metric.key] || defaultOption;
  const label = option.mode === 'change' ? '环比' : option.mode === 'sum' ? metric.scope === 'fx' ? `${option.days}期均值` : `${option.days}日${metric.unit === '%' ? '均值' : '累计'}` : '';
  const scope = metric.scope === 'market' ? markets.find(m => m.code === (option.market || market))?.name : metric.scope === 'equity_market' ? '沪深京已归档个股合计（非全市场覆盖证明）' : metric.scope === 'sample' ? '已归档个股样本' : metric.scope === 'fx' ? `${metric.key.slice(3)} · 归档日线 / 今日Redis盘中` : '当前所选指数';
  return { ...metric, name: metric.name + (label ? `·${label}` : ''), unit: option.mode === 'change' ? '%' : metric.unit,
    description: `${scope || ''} · ${label || '当前值'}${metric.scope === 'fx' ? ' · 历史按来源日期，今日缺归档时可用盘中估算，逐值标明' : ''}${metric.key === 'top_amount_share' ? ` · Top ${option.top}% / ${option.window}交易日` : ''}` };
}
