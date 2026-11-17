import { useState } from 'react';
import { Alert, Button, Empty, InputNumber, Modal, Radio } from 'antd';
import { defaultOption, formatValue, metricColor, type Day, type Metric, type MetricOption, type View } from './model';

export default function MetricSettings({ initialKey, metrics, view, markets, rows, onApply, onClose }: {
  initialKey: string; metrics: Metric[]; view: View; markets: {code: string; name: string}[]; rows: Day[];
  onApply: (settings: View['settings'], thresholds: View['thresholds']) => void; onClose: () => void;
}) {
  const [key, setKey] = useState(initialKey);
  const [settings, setSettings] = useState<View['settings']>(() => structuredClone(view.settings));
  const [thresholds, setThresholds] = useState(() => ({...view.thresholds}));
  const metric = metrics.find(m => m.key === key);
  const option = settings[key] || defaultOption;
  const update = (patch: Partial<MetricOption>) => setSettings(s => ({...s, [key]: {...option, ...patch}}));
  const preview = [...rows].reverse().find(r => r.in_month && r.values[key] != null);
  const changed = JSON.stringify(settings[key]) !== JSON.stringify(view.settings[key]);
  const average = metric?.unit === '%' || metric?.scope === 'fx';
  const period = metric?.scope === 'fx' ? '期' : '日';
  return <Modal title="指标条件设置" open onCancel={onClose} width={780} footer={null}>
    <div className="metric-settings">
      <nav aria-label="已选指标设置列表">{metrics.map(m => <button key={m.key} className={key === m.key ? 'active' : ''} onClick={() => setKey(m.key)}><i style={{background:metricColor(m.key)}} />{m.name}<small>已选</small></button>)}</nav>
      {metric ? <div className="metric-settings-body">
        <h3 style={{color:metricColor(key)}}>{metric.name}</h3>
        <div className="metric-settings-summary"><small>当前摘要</small><b>{metric.scope === 'market' ? markets.find(m => m.code === (option.market || view.market))?.name : metric.scope === 'equity_market' ? '沪深京已归档个股合计' : metric.scope === 'sample' ? `Top ${option.top}% / ${option.window}交易日 · 已归档个股样本` : metric.scope === 'fx' ? `${metric.key.slice(3)} · 已归档日线` : '当前所选指数'} · {option.mode === 'value' ? '当前值' : option.mode === 'change' ? '环比变化（%）' : `${option.days}${period}${average ? '均值' : '累计'}`}</b>
          {changed ? <span>参数尚未应用，确认后重新计算</span> : <span>当前已应用结果 {preview?.date || '—'}：{formatValue(preview?.values[key], option.mode === 'change' ? '%' : metric.unit)}</span>}
        </div>
        {metric.scope === 'market' && <fieldset><legend>数据范围</legend><Radio.Group aria-label={`${metric.name}数据范围`} value={option.market || view.market} onChange={e => update({market:e.target.value})} options={markets.map(m => ({label:m.name,value:m.code}))} /></fieldset>}
        {metric.scope === 'index' && <p className="muted">使用页面当前选择的指数，保留来源口径。</p>}
        {metric.scope === 'equity_market' && <p className="muted">按来源日期汇总已归档沪深京个股成交额，单位为元；独立于所选指数和两融市场。未归档证券不计入，整日无记录或成交额缺值时不计算，不代表官方全市场总额或完整覆盖。</p>}
        {metric.scope === 'fx' && <Alert type="info" title={`收盘报价单位：${metric.unit}`} description="按来源日线日期展示，与A股交易日独立。环比使用前一条已归档日线；N期均值使用最近N条已归档日线。缺行不推断休市或完整覆盖，不使用实时快照补齐。" />}
        {key === 'financing_repayment_ratio' && <Alert type="info" title="买入 / 偿还 × 100%" description="偿还额 = 融资买入额 − 融资净买入额；偿还额非正或数据缺失时不计算。" />}
        {key === 'top_amount_share' && <><fieldset><legend>滚动窗口</legend><InputNumber aria-label="Top滚动窗口" min={1} max={60} precision={0} value={option.window} onChange={v => update({window:v || 1})} /> 个交易日</fieldset><fieldset><legend>Top比例</legend><InputNumber aria-label="Top比例" min={1} max={100} precision={0} value={option.top} onChange={v => update({top:v || 1})} /> %</fieldset><p className="muted">按窗口内个股累计成交额排序，前 Top% 的累计成交额 ÷ 样本同期总成交额。仅统计已归档且有成交的个股，不代表全市场覆盖。</p></>}
        <fieldset><legend>展示口径</legend><Radio.Group aria-label={`${metric.name}展示口径`} value={option.mode} onChange={e => update({mode:e.target.value})} options={[{label:'当前值',value:'value'},{label:'环比变化',value:'change'},{label:average ? `N${period}均值` : '累计N日',value:'sum'}]} /></fieldset>
        {option.mode === 'sum' && <fieldset><legend>{metric.scope === 'fx' ? '统计日线条数' : '统计交易日数'}</legend><InputNumber aria-label="统计期数" min={1} max={60} precision={0} value={option.days} onChange={v => update({days:v || 1})} /></fieldset>}
        <fieldset><legend>高亮阈值（{option.mode === 'change' ? '%' : metric.unit}）</legend><InputNumber aria-label={`${metric.name}高亮阈值`} value={thresholds[key] ?? null} onChange={v => setThresholds(t => {const next={...t}; if(v == null) delete next[key]; else next[key]=Number(v); return next;})} placeholder="留空不高亮" /><p className="muted">大于等于阈值时高亮；{metric.scope === 'fx' ? '环比以前一条已归档日线为基准。' : '环比以前一正式交易日为基准，缺值不跨日补齐。'}</p></fieldset>
        <div className="metric-settings-footer"><Button onClick={onClose}>取消</Button><Button type="primary" onClick={() => onApply(settings, thresholds)}>确认</Button></div>
      </div> : <Empty description="暂无指标目录" />}
    </div>
  </Modal>;
}
