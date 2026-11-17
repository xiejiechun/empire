import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Segmented, Select, Spin, Switch } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DownOutlined, UpOutlined, CloseOutlined, DownloadOutlined, PlusOutlined, SaveOutlined, SettingOutlined } from '@ant-design/icons';
import { chinaToday, configuredMetric, exportCsv, metricColor, loadView, saveView, shiftMonth, type Metric, type MonthResult } from './model';
import { useObservation } from './useObservation';
import { useMonthHistory } from './useMonthHistory';
import { useLiveRefresh } from './useLiveRefresh';
import LiveControls from './LiveControls';
import DayDetails from './DayDetails';
import MetricSettings from './MetricSettings';
import CalendarTimeline from './CalendarTimeline';
import DataSources from './DataSources';
import './observation.css';

type Catalog = { indices: { code: string; name: string }[]; markets: { code: string; name: string }[]; metrics: Metric[] };
export default function ObservationCalendar() {
  const [view, setView] = useState(loadView);
  const [month, setMonth] = useState(chinaToday().slice(0, 7));
  const [search, setSearch] = useState(''), [category, setCategory] = useState('全部');
  const [libraryOpen, setLibraryOpen] = useState(false), [detailDate, setDetailDate] = useState<string>();
  const [focusMode, setFocusMode] = useState(false), [focusedMetric, setFocusedMetric] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const locateToday = useRef(false);
  const [settings, setSettings] = useState<string>(), [notice, setNotice] = useState('');
  const catalog = useObservation<Catalog>('observation.catalog', {});
  const indices = catalog.data?.indices || [], metrics = catalog.data?.metrics || [];
  const index = indices.some(i => i.code === view.index) ? view.index : (indices.find(i => i.name === '上证指数') || indices[0])?.code || '';
  const quickIndices = ['中证全指', '上证指数', '深证成指', '创业板指', '科创50', '北证50', '上证50', '沪深300', '中证500', '中证1000', '中证2000']
    .map(name => indices.find(i => i.name === name)).filter((i): i is Catalog['indices'][number] => !!i);
  const params = { month, index, market: view.market, settings: view.settings, include_top: view.selected.includes('top_amount_share'), include_turnover: view.selected.includes('market_amount'), include_fx: view.selected.filter(k => k.startsWith('fx_')) };
  const result = useObservation<MonthResult>('observation.read', params, !!index);
  const history = useMonthHistory(result.identity, result.data, params);
  const live = useLiveRefresh(result.identity, result.data ? [...history.months, result.data] : []);
  const months = live.months;
  const detailRows = [...new Map(months.flatMap(m => m.rows).sort((a, b) => Number(a.in_month) - Number(b.in_month)).map(r => [r.date, r])).values()].sort((a, b) => a.date.localeCompare(b.date));
  const selected = view.selected.map(k => metrics.find(m => m.key === k)).filter((m): m is Metric => !!m).map(m => configuredMetric(m, view.settings, catalog.data?.markets || [], view.market));
  const indexName = indices.find(i => i.code === index)?.name || '指数';
  const marketName = catalog.data?.markets.find(i => i.code === view.market)?.name || '';
  const update = (patch: Partial<typeof view>) => { setView(v => ({ ...v, ...patch })); setNotice(''); };
  useEffect(() => { if (index && index !== view.index) setView(v => ({ ...v, index })); }, [index, view.index]);
  const move = (key: string, offset: number) => {
    const keys = selected.map(m => m.key), pos = keys.indexOf(key), target = pos + offset;
    if (target < 0 || target >= keys.length) return;
    [keys[pos], keys[target]] = [keys[target], keys[pos]]; update({ selected: keys });
  };
  const retry = () => { setDetailDate(undefined); catalog.refresh(); result.refresh(); };
  useEffect(() => setDetailDate(undefined), [month, index, view.market, view.settings]);
  const visibleMetrics = metrics.filter(m => (category === '全部' || category === m.category) && m.name.includes(search.trim()));
  const quoteDays = result.data?.rows.filter(r => r.in_month && r.values.close != null).length;
  const detailIndex = detailRows.findIndex(r => r.date === detailDate);
  const detailDay = detailRows[detailIndex];
  const explanations = [...new Set(result.data?.warnings || [])];
  if (selected.some(m => m.scope === 'fx')) explanations.push('汇率历史按来源日线日期展示；今天缺归档时补已有Redis报价，顶部集中标识，详情保留逐值来源；环比和均值为盘中估算。自动刷新仅更新Redis，归档基准通过“刷新数据”更新。A股休市仍可有报价，缺行不代表休市。');
  const tracked = selected.some(m => m.key === focusedMetric) ? focusedMetric : null;
  const goToday = () => {
    const today = chinaToday();
    if (month === today.slice(0, 7) && result.data) scrollRef.current?.querySelector(`[data-month="${month}"] [data-date="${today}"]`)?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    else { locateToday.current = true; setMonth(today.slice(0, 7)); }
  };
  useEffect(() => {
    if (locateToday.current && result.data?.month === chinaToday().slice(0, 7)) {
      locateToday.current = false;
      scrollRef.current?.querySelector(`[data-month="${result.data.month}"] [data-date="${chinaToday()}"]`)?.scrollIntoView({ block: 'center', inline: 'nearest' });
    }
  }, [result.data]);
  return <section className={`observation-page density-${view.density} ${focusMode ? "focus-mode" : ""}`} aria-label="多指标观察日历">
    <div className="observation-heading"><div><div className="observation-breadcrumb">市场观察 / 月度视图</div><h1>多指标观察日历</h1><span className="muted">对照每日行情与资金变化，让观察更有条理</span></div><div className="observation-actions">
      <Button className="focus-toggle" aria-pressed={focusMode} onClick={() => setFocusMode(v => !v)}>{focusMode ? '退出专注' : '专注月历'}</Button>
      <LiveControls live={live} />
      <Button icon={<SaveOutlined />} onClick={() => { try { saveView({ ...view, index }); setNotice('已保存本机视图：指数、市场、指标顺序、密度和阈值；下次打开自动恢复。'); } catch { setNotice('视图保存失败，请检查本机存储是否可用。'); } }}>保存视图</Button>
      <Button icon={<DownloadOutlined />} disabled={!result.data || !selected.length} onClick={() => result.data && exportCsv(months[months.length - 1].rows, selected, index, marketName, month)}>导出数据</Button>
      <Button onClick={retry} loading={result.loading}>刷新数据</Button></div></div>
    <div className="observation-content">
    {(catalog.error || result.error) && <Alert showIcon type="error" title="日历读取失败" description={catalog.error || result.error} action={<Button onClick={retry}>重试</Button>} />}
    {notice && <Alert type="info" title={notice} closable onClose={() => setNotice('')} />}
    <div className="observation-indexbar"><div className="observation-index-select"><span className="field-caption">观察指数</span>
      <Select aria-label="观察指数" showSearch optionFilterProp="label" value={index || undefined} placeholder="选择已有指数" style={{ width: 195 }}
        options={indices.map(i => ({ value: i.code, label: `${i.name} · ${i.code}` }))} onChange={index => update({ index })} /></div><div className="observation-index-shortcuts">
      {quickIndices.map(i => <button key={i.code} className={index === i.code ? 'active' : ''} onClick={() => update({ index: i.code })}><b>{i.name}</b><small>{i.code}</small></button>)}
      </div>
    </div>
    <div className="observation-toolbar"><div className="observation-month-controls">
      <input aria-label="观察月份" type="month" min="1991-01" max="2099-12" value={month} onChange={e => { if (/^(199[1-9]|20\d{2})-(0[1-9]|1[0-2])$/.test(e.target.value)) setMonth(e.target.value); }} />
      <Button disabled={month === '1991-01'} onClick={() => setMonth(shiftMonth(month, -1))}>上月</Button>
      <Button onClick={() => setMonth(chinaToday().slice(0, 7))}>本月</Button>
      <Button disabled={month === '2099-12'} onClick={() => setMonth(shiftMonth(month, 1))}>下月</Button></div><div className="observation-market-controls">
      <span className="muted">两融口径</span><Select aria-label="两融市场" value={view.market} options={catalog.data?.markets.map(m => ({ value: m.code, label: m.name }))} onChange={market => update({ market })} style={{ width: 135 }} /></div>
      <span className="flex-gap" />
      <Segmented aria-label="显示密度" options={['紧凑', '标准', '详细']} value={view.density} onChange={density => update({ density })} />
      <label>异常高亮 <Switch size="small" checked={view.highlight} onChange={highlight => update({ highlight })} /></label>

    </div>
    <div className="observation-selection">
      <span className="field-caption">观察指标 <b>{selected.length}</b></span>
      <div className="observation-chips">{selected.map(m => <button className={`observation-chip ${tracked === m.key ? 'active' : ''}`} aria-label={`追踪${m.name}`} aria-pressed={tracked === m.key} title="点击突出整月同一指标，再次点击取消" key={m.key} onClick={() => setFocusedMetric(current => current === m.key ? null : m.key)}><i style={{ background: metricColor(m.key) }} />{m.name}</button>)}{!selected.length && <span className="muted">点击管理指标，添加想要观察的数据</span>}</div>
      <Button className="manage-metrics" aria-expanded={libraryOpen} aria-controls="observation-library" icon={libraryOpen ? <UpOutlined /> : <DownOutlined />} onClick={() => setLibraryOpen(v => !v)}>{libraryOpen ? '收起指标' : '管理指标'}</Button>
    </div>
    {libraryOpen && <div className="observation-library" id="observation-library">
      <div className="metric-library"><div className="metric-library-title"><strong>指标库 <small>{metrics.length} 个指标</small></strong><Input aria-label="搜索指标" placeholder="搜索指标名称" value={search} onChange={e => setSearch(e.target.value)} allowClear style={{ width: 200 }} /></div>
        <Segmented options={['全部', '行情', '成交', '资金', '汇率']} value={category} onChange={setCategory} />
        <div className="metric-cards">{visibleMetrics.map(m => <button key={m.key} disabled={view.selected.includes(m.key)} onClick={() => update({ selected: [...view.selected, m.key] })}>
          <span><i style={{ background: metricColor(m.key) }} /><b>{m.name}</b></span><small>同花顺 · {m.scope === 'index' ? '所选指数' : m.scope === 'equity_market' ? '沪深京归档样本' : m.scope === 'sample' ? '已归档样本' : m.scope === 'fx' ? m.key.slice(3) : marketName} · {m.unit}</small><span className="metric-add">{view.selected.includes(m.key) ? '已添加' : <PlusOutlined />}</span>
        </button>)}{!visibleMetrics.length && <div className="metric-search-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配指标" /><Button type="link" onClick={() => { setSearch(''); setCategory('全部'); }}>清除筛选</Button></div>}</div>
      </div>
      <div className="selected-metrics"><strong>已选指标 <small>{selected.length} 项</small></strong>
        {!selected.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从左侧添加观察指标" />}
        {selected.map((m, i) => <div className="selected-metric" key={m.key}><span className="metric-order">{i + 1}</span><span className="metric-description"><b>{m.name}</b><small>{m.description} · {m.unit}</small></span>
          <Button className="metric-settings-trigger" type="text" size="small" aria-label={`设置${m.name}`} icon={<SettingOutlined />} onClick={() => setSettings(m.key)}>设置</Button>
          <Button type="text" size="small" aria-label={`上移${m.name}`} disabled={i === 0} icon={<ArrowUpOutlined />} onClick={() => move(m.key, -1)} />
          <Button type="text" size="small" aria-label={`下移${m.name}`} disabled={i === selected.length - 1} icon={<ArrowDownOutlined />} onClick={() => move(m.key, 1)} />
          <Button type="text" size="small" aria-label={`移除${m.name}`} icon={<CloseOutlined />} onClick={() => update({ selected: view.selected.filter(k => k !== m.key) })} />
        </div>)}
      </div>
    </div>}
    <div className="observation-note"><span>行情 · <b>{indexName}</b><span className="note-divider">/</span>两融 · <b>{marketName}</b>{quoteDays != null && <span className="quote-days">当月已有行情 {quoteDays} 日</span>}</span><span className="observation-read-actions">
      <DataSources month={month} explanations={explanations} />
      <Button type="link" size="small" onClick={goToday}>定位今天</Button>{tracked && <Button type="link" size="small" onClick={() => setFocusedMetric(null)}>取消指标追踪</Button>}<span>{result.data && `读取于 ${new Date(result.data.queried_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}`}</span></span></div>
    {(catalog.loading || result.loading) && <div className="observation-loading"><Spin /> 正在读取月历…</div>}
    {!catalog.loading && !catalog.error && !indices.length && <Empty description="尚无指数目录，请先在采集管理中完成指数列表采集" />}
    {result.data && <CalendarTimeline key={result.identity} months={months} loading={history.loading} error={history.error} hasPrevious={history.hasPrevious} onLoadPrevious={history.loadPrevious} metrics={selected} indexName={indexName} marketName={marketName}
      thresholds={view.thresholds} highlight={view.highlight} focusedMetric={tracked} selectedDate={detailDate} onOpen={setDetailDate} scrollRef={scrollRef} />}
    <div className="observation-legend"><span><i className="legend-today" />今天</span><span><i className="legend-closed" />正式休市</span><span>— 未取得可用值</span><span>量额保留来源口径 · 点击日期查看原值 · 点击指标标签追踪</span></div>
    </div>
    <DayDetails day={detailDay} metrics={selected} indexName={indexName} marketName={marketName} onClose={() => setDetailDate(undefined)} previousDate={detailIndex > 0 ? detailRows[detailIndex - 1].date : undefined} nextDate={detailIndex >= 0 ? detailRows[detailIndex + 1]?.date : undefined} onNavigate={setDetailDate} />
    {settings && <MetricSettings initialKey={settings} metrics={view.selected.map(k => metrics.find(m => m.key === k)).filter((m): m is Metric => !!m)} view={view} markets={catalog.data?.markets || []} rows={result.data?.rows || []}
      onClose={() => setSettings(undefined)} onApply={(settings, thresholds) => { update({settings, thresholds}); setSettings(undefined); }} />}
  </section>;
}
