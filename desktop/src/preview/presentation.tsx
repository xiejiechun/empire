import { Button, Table, Tag } from "antd";
import type { Data } from "../api";

export type PreviewProps = {
  spec: Data;
  rows: Data[];
  context?: Data;
  onNavigate?: (view: string, filters: Data) => void;
};
export type Field = { key: string; label: string; kind?: string; unit?: string };
export const numberKinds = new Set(["number", "num", "decimal", "integer"]);
export const longKinds = new Set(["longtext", "url"]);

const labels: Record<string, string> = {
  SH: "沪市", SZ: "深市", BJ: "北交所", CN: "全国", MAIN: "主板", STAR: "科创板",
  CHINEXT: "创业板", ALL: "全部板块", current: "当期持有", exited: "退出名单",
  buy: "买入", sell: "卖出", source_report: "来源报表", year_to_date: "年初至今",
  instant: "期末时点", CNY: "人民币", ordinary: "普通交易", exemptions: "豁免情形",
  limit_ratio: "涨跌幅限制", rounding: "价格舍入", resale_constraint: "买入后卖出限制",
  buy_minimum: "买入最低数量", buy_increment: "买入递增数量", odd_lot: "零股处理",
  star_orders: "申报数量", maximum: "最大申报数量", price_tick: "最小价格变动",
  open_auction: "开盘集合竞价", continuous_am: "上午连续竞价", continuous_pm: "下午连续竞价",
  close_auction: "收盘集合竞价", after_hours: "盘后交易", buy_rate: "买入费率",
  sell_rate: "卖出费率", basis: "计费依据", minimum: "最低收费", ratio: "比例",
  shares: "股", text: "条款", "Asia/Shanghai": "北京时间", period: "定期报告", periodic: "定期报告",
  change_notice: "变动公告", available: "已提供", unavailable: "来源未提供",
  complete: "详情已归档", missing: "详情待补齐", empty: "来源返回空集合", incomplete: "来源资料不完整",
  source_empty: "来源无席位明细", present: "来源详情已提供", partial: "来源部分缺失",
  no_content: "来源未提供正文", B: "买入", S: "卖出",
};

export function display(value: any, field?: Field): string {
  if (value == null || value === "") return "—";
  if (field?.kind === "time" && (value === 0 || value === "0" || /^1970-01-01[T ]08:00:00(?:[+.].*)?$/.test(String(value)))) return "未知（来源0）";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(v => display(v)).join("、") || "—";
  if (typeof value === "object") return "—";
  const raw = String(value);
  if (field?.kind === "time" && /^\d{10}$/.test(raw))
    return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(Number(raw) * 1000);
  if (/^-?\d+(\.\d+)?$/.test(raw) && numberKinds.has(field?.kind || "")) {
    const [whole, decimal] = raw.split(".");
    return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (decimal == null ? "" : "." + decimal);
  }
  return labels[raw] || raw;
}

export function fields(spec: Data): Field[] { return spec.columns || []; }
export function rowIdentity(row: Data, spec: Data, index = 0): string {
  const values = (spec.identity || []).map((key: string) => row[key] ?? "");
  return values.some((value: any) => value !== "") ? values.join("|") : String(index);
}
export function detailFilters(spec: Data, row: Data): Data {
  return Object.fromEntries(Object.entries(spec.detailFilters || {}).map(([filter, key]) => [filter, String(row[String(key)] ?? "")]));
}
export function OpenDetail({ spec, row, onNavigate }: { spec: Data; row: Data; onNavigate?: PreviewProps["onNavigate"] }) {
  return spec.detailView && onNavigate ? <Button type="link" size="small" onClick={() => onNavigate(spec.detailView, detailFilters(spec, row))}>查看{spec.detailLabel || "明细"} →</Button> : null;
}
export function Facts({ row, columns }: { row: Data; columns: Field[] }) {
  return <dl className="pv-facts">{columns.map(field => <div key={field.key} className={longKinds.has(field.kind || "") ? "pv-fact-wide" : ""}>
    <dt>{field.label}{field.unit ? `（${field.unit}）` : ""}</dt>
    <dd>{display(row[field.key], field)}</dd>
  </div>)}</dl>;
}
export function RecordTable({ rows, spec, onSelect, onNavigate, columns }: PreviewProps & { onSelect?: (row: Data) => void; columns?: Field[] }) {
  const declared = columns || fields(spec);
  return <div className="pv-table"><Table<Data> size="small" dataSource={rows} pagination={false}
    rowKey={(row, i) => rowIdentity(row, spec, i)} scroll={{ x: "max-content" }}
    onRow={row => ({ onDoubleClick: () => onSelect?.(row) })}
    columns={[
      ...declared.map(field => ({ key: field.key, dataIndex: field.key,
        title: <span>{field.label}{field.unit && <small className="pv-unit">{field.unit}</small>}</span>,
        width: longKinds.has(field.kind || "") ? 330 : field.kind === "date" ? 132 : 160,
        render: (value: any, row: Data) => <span className={numberKinds.has(field.kind || "") ? "pv-number" : ""}
          title={field.key === "quantity" && row.quantity_scale != null && row.quantity_decimals != null ? `来源最小数值刻度约 ${Number(row.quantity_scale) * 10 ** -Number(row.quantity_decimals)} ${field.unit || ""}` : undefined}>
          {display(value, field)}</span>,
      })),
      ...(onSelect || spec.detailView ? [{ key: "action", title: "查看", width: 116, fixed: "right" as const,
        render: (_: any, row: Data) => onSelect ? <Button type="link" size="small" onClick={() => onSelect(row)}>展开记录</Button> : <OpenDetail spec={spec} row={row} onNavigate={onNavigate} /> }] : []),
    ]} /></div>;
}
export function Metric({ label, value, unit }: { label: string; value: any; unit?: string }) {
  return <div className="pv-metric"><span>{label}</span><strong>{display(value, { key: "", label, kind: "number" })}<small>{unit}</small></strong></div>;
}
export function Security({ row }: { row: Data }) {
  return <span className="pv-security"><strong>{row.name || row.stock_name || row.instrument_name || row.index_name || row.unified_code || row.code || "记录"}</strong>
    <small>{row.unified_code || row.index_code || [row.code, row.market].filter(Boolean).join(".")}</small></span>;
}
export function Flag({ value }: { value: any }) { return <Tag>{display(value)}</Tag>; }
