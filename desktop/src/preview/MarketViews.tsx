import { useState } from "react";
import { Select, Tag } from "antd";
import { Data } from "../api";
import { display, Metric, PreviewProps, RecordTable } from "./presentation";

export function PriceView({ spec, rows, context, onNavigate }: PreviewProps) {
  const [selected, setSelected] = useState("");
  const code = (row: Data) => row.unified_code || row.index_code || row.code || context?.security || context?.filters?.security || "当前证券";
  const securities = [...new Set(rows.map(code))];
  const selectedCode = securities.includes(selected) ? selected : securities.length === 1 ? securities[0] : "";
  const chosen = rows.filter(row => code(row) === selectedCode).sort((a, b) => String(a.trade_date).localeCompare(String(b.trade_date)));
  const validDates = chosen.every(row => /^\d{4}-\d{2}-\d{2}$/.test(row.trade_date)) && new Set(chosen.map(row => row.trade_date)).size === chosen.length;
  const close = chosen.map(row => row.close == null || String(row.close).trim() === "" ? null : Number(row.close));
  const finite = close.filter((v): v is number => v != null && Number.isFinite(v));
  const min = Math.min(...finite), max = Math.max(...finite), span = max - min || Math.abs(max) * .02 || 1;
  const x = (i: number) => 72 + i * 848 / Math.max(chosen.length - 1, 1);
  const y = (v: number) => 178 - (v - min) / span * 140;
  const paths: string[] = []; let path = "";
  close.forEach((value, index) => {
    if (value == null || !Number.isFinite(value)) { if (path) paths.push(path); path = ""; }
    else path += `${path ? " L" : "M"}${x(index)},${y(value)}`;
  });
  if (path) paths.push(path);
  const last = chosen.at(-1);
  return <div className="pv-prices">
    <div className="pv-section-heading"><div><h3>收盘价走势</h3><span className="pv-subtle">当前页 · 按交易日期升序展示，缺值断开</span></div>
      {securities.length > 1 && <Select aria-label="走势证券" value={selectedCode || undefined} placeholder="选择证券查看走势" style={{ width: 230 }} onChange={setSelected}
        options={securities.map(value => ({ value, label: value }))} />}
      {securities.length === 1 && <Tag>{selectedCode}</Tag>}
    </div>
    {selectedCode && validDates && finite.length ? <>
      <div className="pv-metrics"><Metric label={`本页末日 ${last?.trade_date}`} value={last?.close} unit="收盘" /><Metric label="开盘" value={last?.open} /><Metric label="最高" value={last?.high} /><Metric label="最低" value={last?.low} /></div>
      <svg className="pv-price-chart" viewBox="0 0 960 230" role="img" aria-label="本页收盘价走势">
        {[min, min + span / 2, min + span].map((v, i) => <g key={i}><line x1="72" y1={y(v)} x2="920" y2={y(v)} stroke="#e8eef3" /><text x="62" y={y(v) + 4} textAnchor="end">{v.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}</text></g>)}
        {paths.map((d, i) => <path key={i} d={d} fill="none" stroke="#237c91" strokeWidth="2.5" />)}
        {chosen.map((row, i) => close[i] != null && Number.isFinite(close[i]) && <circle key={row.trade_date} cx={x(i)} cy={y(close[i]!)} r="3" fill="#237c91"><title>{row.trade_date} · 收盘 {row.close}</title></circle>)}
        <text x="72" y="213">{chosen[0]?.trade_date}</text><text x="920" y="213" textAnchor="end">{last?.trade_date}</text>
      </svg>
    </> : <div className="pv-chart-prompt">{!selectedCode ? "本页包含多只证券，请先选择一只查看走势。" : "缺少有效、唯一的日期及收盘价，暂不绘制走势。"}</div>}
    <h3 className="pv-section-title">每日价格与成交</h3><RecordTable spec={spec} rows={rows} onNavigate={onNavigate} />
  </div>;
}

export function CalendarView({ rows, context }: PreviewProps) {
  const month = context?.month || context?.filters?.month || rows[0]?.trade_date?.slice(0, 7);
  if (!/^\d{4}-\d{2}$/.test(month || "")) return <p className="pv-note">请选择月份查看日历。</p>;
  const [year, monthNumber] = month.split("-").map(Number);
  const offset = (new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const records = new Map<string, Data>();
  const duplicates = new Set<string>();
  for (const row of rows) {
    if (!String(row.trade_date).startsWith(month + "-")) continue;
    if (records.has(row.trade_date)) duplicates.add(row.trade_date);
    records.set(row.trade_date, row);
  }
  for (const day of duplicates) records.delete(day);
  const days = Array.from({ length: count }, (_, index) => `${month}-${String(index + 1).padStart(2, "0")}`);
  const trading = days.filter(day => records.get(day)?.is_trade === true).length;
  const rest = days.filter(day => records.get(day)?.is_trade === false).length;
  return <div className="pv-calendar">
    <div className="pv-section-heading"><h3>{month} · A 股交易安排</h3><div><Tag color="cyan">交易日</Tag><Tag>休市日</Tag><Tag color="gold">未知</Tag></div></div>
    <div className="pv-metrics"><Metric label="交易日" value={trading} unit="天" /><Metric label="休市日" value={rest} unit="天" /><Metric label="未取得数据" value={count - trading - rest} unit="天" /></div>
    {duplicates.size > 0 && <p role="alert" className="pv-warning">存在重复日期，相关日期显示为未知，请核查来源记录。</p>}
    <div className="pv-calendar-grid" role="grid" aria-label={`${month}交易日历`}>
      {["一", "二", "三", "四", "五", "六", "日"].map(day => <div role="columnheader" className="pv-calendar-weekday" key={day}>周{day}</div>)}
      {Array.from({ length: offset }, (_, i) => <div role="gridcell" className="pv-calendar-blank" key={`blank-${i}`} />)}
      {Array.from({ length: count }, (_, index) => {
        const date = `${month}-${String(index + 1).padStart(2, "0")}`;
        const row = records.get(date); const state = row?.is_trade === true ? "trade" : row?.is_trade === false ? "rest" : "unknown";
        return <div role="gridcell" key={date} className={`pv-calendar-day ${state}`} aria-label={`${date} ${state === "trade" ? "交易日" : state === "rest" ? "休市日" : "未知"}`}>
          <strong>{index + 1}</strong><span>{state === "trade" ? "交易" : state === "rest" ? "休市" : "未知"}</span>
          <small>{row?.updated_at ? `更新 ${display(row.updated_at).slice(5, 10)}` : row ? "来源已记录" : "未取得来源记录"}</small>
        </div>;
      })}
    </div><p className="pv-note">按来源记录展示，空白日期不按周末推断。未来安排仍可能修订。</p>
  </div>;
}
