import { useState } from "react";
import { Button, Segmented, Tag } from "antd";
import { Data } from "../api";
import { display, Facts, Field, fields, Metric, OpenDetail, PreviewProps, RecordTable, Security } from "./presentation";

const memberFields: Field[] = [
  { key: "source_rank", label: "来源名次" }, { key: "holder_name", label: "持有人", kind: "text" },
  { key: "quantity", label: "持有数量", kind: "number" }, { key: "ratio", label: "持有比例", kind: "number", unit: "%" },
  { key: "change_quantity", label: "持有数量变动", kind: "number" }, { key: "change_label", label: "变动类型" },
  { key: "actual_change", label: "实际变动", kind: "text" }, { key: "share_type", label: "股份类型" },
  { key: "pledge_ratio", label: "质押比例", unit: "%", kind: "number" }, { key: "pledge_status", label: "质押状态" },
];

export function HoldingsView({ spec, rows, onNavigate }: PreviewProps) {
  const [group, setGroup] = useState("current");
  const detail = rows.find(row => Array.isArray(row.members));
  if (!detail) return <div className="pv-report-list">{rows.map((row, i) => <article className="pv-report-card" key={row.report_key || i}>
    <div className="pv-section-heading"><Security row={row} /><Tag>{row.report_date}</Tag></div>
    <div className="pv-metrics"><Metric label="当期持有人" value={row.member_count} unit="位" /><Metric label="退出名单" value={row.exit_count} unit="位" />
      <Metric label="来源合计持有比例" value={row.total_ratio} unit="%" /></div>
    <div className="pv-card-footer"><span className="pv-subtle">{display(row.report_type)} · {row.instrument_name || "股票"}{row.quality_flags ? " · 含来源质量提示" : ""}</span><OpenDetail spec={spec} row={row} onNavigate={onNavigate} /></div>
  </article>)}</div>;
  const members = detail.members.filter((member: Data) => member.member_group === group);
  const unit = detail.kind === "bond_holders" ? "张" : "股";
  return <div className="pv-holdings-detail"><div className="pv-section-heading"><Security row={detail} /><Tag>{detail.report_date} · {display(detail.report_type)}</Tag></div>
    <div className="pv-metrics"><Metric label="来源合计持有数量" value={detail.total_quantity} unit={unit} /><Metric label="来源合计持有比例" value={detail.total_ratio} unit="%" /></div>
    {detail.quality_flags ? <p className="pv-warning">本报告带有来源质量标记（{detail.quality_flags}），未知数量和比例保留为空，不将缺值视为零。</p> : null}
    <div className="pv-tool-row"><Segmented aria-label="持有人名单类型" value={group} onChange={value => setGroup(String(value))} options={[
      { value: "current", label: `当期持有 ${detail.members.filter((m: Data) => m.member_group === "current").length}` },
      { value: "exited", label: `退出名单 ${detail.members.filter((m: Data) => m.member_group === "exited").length}` },
    ]} /><span className="pv-subtle">数量单位：{unit}；比例口径：{display(detail.ratio_basis)}</span></div>
    {group === "current" && members.some((m: Data) => m.ratio != null) && <div className="pv-holding-bars" aria-label="当期持有比例">
      {members.map((m: Data, i: number) => <div className="pv-holding-bar" key={`${m.seq}-${i}`}><span>{m.holder_name}</span><div><i style={{ width: `${Math.max(0, Math.min(100, Number(m.ratio) || 0))}%` }} /></div><strong>{display(m.ratio)}{m.ratio == null ? "" : "%"}</strong></div>)}
    </div>}
    <RecordTable rows={members} spec={{ identity: ["member_group", "seq"] }} columns={memberFields.map(f => ["quantity", "change_quantity"].includes(f.key) ? { ...f, unit } : f)} />
    <p className="pv-note">当期名单与退出名单分别展示。变动公告不等同于完整前十名报告；比例条仅辅助阅读，不对缺值推算。</p>
  </div>;
}

const reasonFields: Field[] = [
  { key: "reason_code", label: "原因编号" }, { key: "reason", label: "上榜原因", kind: "longtext" }, { key: "close_price", label: "收盘价", kind: "number", unit: "元" },
  { key: "change_pct", label: "涨跌幅", unit: "%", kind: "number" }, { key: "volume", label: "来源成交量", kind: "number", unit: "万（来源口径）" },
  { key: "turnover", label: "来源成交额", kind: "number", unit: "万元" },
];
const seatFields: Field[] = [
  { key: "reason_code", label: "原因编号" }, { key: "seat_rank", label: "名次" }, { key: "seat_name", label: "营业部 / 机构", kind: "text" },
  { key: "buy_amount", label: "买入额", unit: "万元", kind: "number" }, { key: "sell_amount", label: "卖出额", unit: "万元", kind: "number" },
  { key: "net_amount", label: "净额", unit: "万元", kind: "number" }, { key: "source_tags", label: "来源标签", kind: "longtext" },
];
export function HotListView({ spec, rows, onNavigate }: PreviewProps) {
  const [side, setSide] = useState("B");
  const detail = rows.find(row => Array.isArray(row.seats));
  if (!detail) return <div className="pv-hot-list"><div className="pv-card-grid">{rows.map((row, i) => <article className="pv-event-card" key={`${row.unified_code}-${row.list_date}-${i}`}>
    <div className="pv-section-heading"><Security row={row} /><Tag>{row.list_date}</Tag></div>
    <div className="pv-metrics"><Metric label="上榜原因" value={row.reason_count} unit="项" /><Metric label="席位记录" value={row.seat_count} unit="条" /></div>
    <div className="pv-card-footer"><Tag>{display(row.detail_status)}</Tag><OpenDetail spec={spec} row={row} onNavigate={onNavigate} /></div>
  </article>)}</div></div>;
  const seats = detail.seats.filter((row: Data) => row.side === side).map((row: Data) => ({ ...row,
    source_tags: ["bq1", "bq2", "bq3", "bq4"].map(k => row.extension?.[k]).filter(Boolean),
  }));
  const auxiliary = detail.auxiliary || {};
  return <div className="pv-hot-detail"><div className="pv-section-heading"><Security row={detail} /><div><Tag>{detail.list_date}</Tag><Tag>{display(detail.detail_status || detail.status)}</Tag></div></div>
    {(detail.detail_status || detail.status) === "source_empty" && detail.seats.length > 0 && <p className="pv-warning" role="alert">本轮来源未提供席位明细。下方保留的是上次有效的原因与席位，仅供历史参考，不代表本轮来源已提供完整详情。</p>}
    {(detail.detail_status || detail.status) === "partial" && <p className="pv-warning" role="alert">来源部分缺失或原因关联存在歧义。下方保留各条来源记录，不将已归档等同于数据完整。</p>}
    <h3 className="pv-section-title">上榜原因</h3><RecordTable rows={detail.reasons || []} spec={{ identity: ["seq"] }} columns={reasonFields} />
    <div className="pv-section-heading"><h3>成交席位</h3><Segmented aria-label="龙虎榜买卖方向" value={side} onChange={v => setSide(String(v))} options={[{ value: "B", label: "买入榜" }, { value: "S", label: "卖出榜" }]} /></div>
    <RecordTable rows={seats} spec={{ identity: ["seq"] }} columns={seatFields} />
    {!seats.length && <p className="pv-note">该方向暂无已归档席位记录。</p>}
    {(auxiliary.counts?.length || auxiliary.related?.length || auxiliary.institution_count != null) ? <details className="pv-more"><summary>来源辅助信息（查询时刻口径）</summary>
      <Metric label="来源机构活动次数" value={auxiliary.institution_count} unit="次" />
      {auxiliary.counts?.length ? <RecordTable rows={auxiliary.counts.map(([name, count]: [string, number]) => ({ name, count }))} spec={{ identity: ["name"] }} columns={[{ key: "name", label: "营业部 / 机构" }, { key: "count", label: "活动次数", kind: "integer", unit: "次" }]} /> : null}
      {auxiliary.related?.length ? <RecordTable rows={auxiliary.related.map((r: any[], i: number) => ({ seq: i, day: r[0], code: r[1], reason_code: r[2], seat_name: r[3], side: r[4], rank: r[5], label: r[6] }))} spec={{ identity: ["seq"] }} columns={[
        { key: "day", label: "日期", kind: "date" }, { key: "code", label: "证券代码" }, { key: "reason_code", label: "原因编号" }, { key: "seat_name", label: "席位名称" }, { key: "side", label: "方向" }, { key: "rank", label: "名次", kind: "integer" }, { key: "label", label: "关联标签" },
      ]} /> : null}
    </details> : null}
    <p className="pv-note">同一证券可因多条原因上榜；席位按来源原因和方向保留，不能跨原因简单相加。</p>
  </div>;
}

export function NewsView({ rows }: PreviewProps) {
  const [selected, setSelected] = useState<string>();
  const current = rows.find(row => String(row.news_id) === selected) || rows[0];
  if (!current) return null;
  return <div className="pv-reader pv-news"><div className="pv-reader-list" role="list" aria-label="财经快讯列表">{rows.map((row, index) => <button type="button" className={row === current ? "selected" : ""} key={row.news_id || index}
    onClick={() => setSelected(String(row.news_id))} aria-pressed={row === current}>
    <time>{display(row.published_at).replace("T", " ")}</time><strong>{row.is_important ? "● " : ""}{row.title || String(row.content || "").slice(0, 70)}</strong>
    <span>{String(row.content || "").slice(0, 110)}</span></button>)}</div>
    <article className="pv-reader-article"><div className="pv-tool-row"><time>{display(current.published_at).replace("T", " ")}</time>{current.is_important && <Tag color="red">重要</Tag>}</div>
      <h2>{current.title || "财经快讯"}</h2><div className="pv-news-body">{current.content || "来源未提供正文"}</div>
      <div className="pv-tool-row">{Array.isArray(current.tags) && current.tags.map((tag: any, i: number) => <Tag key={i}>{typeof tag === "object" ? tag.name || tag.title || "" : tag}</Tag>)}</div>
      <div className="pv-subtle">来源修订时间：{display(current.source_updated_at)}<br />当前版本观测时间：{display(current.version_observed_at)}</div>
    </article></div>;
}

export function EventView({ spec, rows, context, onNavigate }: PreviewProps) {
  const [selected, setSelected] = useState<Data>();
  const current = selected && rows.includes(selected) ? selected : rows[0];
  if (!current) return null;
  if (spec.hidden) return <div className="pv-detail-records">{rows.map((row, i) => <article className="pv-record-detail" key={row.record_key || i}>
    {rows.length > 1 && <h3>明细 {i + 1}</h3>}
    {Object.hasOwn(row, "last_valid") && <div className="pv-warning">当前来源状态：{display(row.detail_status)}。{row.last_valid ? "下面单独保留上次有效资料，不代表本轮已取得完整资料。" : "尚无可用的历史资料。"}
      {row.missing_fields?.length ? ` 缺少字段：${row.missing_fields.map((key: string) => fields(spec).find(f => f.key === key)?.label || key).join("、")}` : ""}</div>}
    <Facts row={row} columns={fields(spec).filter(f => f.key !== "history")} />
    {row.history && <><h3 className="pv-section-title">公司历史沿革</h3><div className="pv-news-body">{String(row.history)}</div></>}
    {row.last_valid && <><h3 className="pv-section-title">上次有效资料</h3><Facts row={row.last_valid} columns={fields(spec).filter(f => f.key !== "history")} />
      {row.last_valid.history && <><h3 className="pv-section-title">上次有效历史沿革</h3><div className="pv-news-body">{String(row.last_valid.history)}</div></>}</>}
    {Array.isArray(row.releases) && <><h3 className="pv-section-title">解除记录</h3><RecordTable rows={row.releases} spec={{ identity: ["record_key"] }} columns={[
      { key: "event_date", label: "公告日 / 报告期", kind: "date" }, { key: "actual_date", label: "实际解除日期", kind: "date" },
      { key: "quantity", label: "本次解除股数", kind: "decimal", unit: "股" }, { key: "description", label: "解除说明", kind: "longtext" },
      { key: "in_window", label: "来源当前窗口", kind: "boolean" },
    ]} /></>}
  </article>)}</div>;
  const dateField = fields(spec).find(f => f.kind === "date");
  const titleField = fields(spec).find(f => f.kind === "text" && !["unified_code", "code"].includes(f.key));
  return <div className="pv-events"><div className="pv-reader">
    <div className="pv-reader-list" role="list" aria-label="事件列表">{rows.map((row, i) => <button type="button" key={i} className={row === current ? "selected" : ""} aria-pressed={row === current} onClick={() => setSelected(row)}>
      <time>{dateField ? display(row[dateField.key]) : `记录 ${i + 1}`}</time><Security row={{ unified_code: context?.filters?.security, ...row }} />
      <span>{titleField ? display(row[titleField.key]) : spec.title}</span>
    </button>)}</div>
    <article className="pv-reader-article"><div className="pv-section-heading"><Security row={{ unified_code: context?.filters?.security, ...current }} /><OpenDetail spec={spec} row={current} onNavigate={onNavigate} /></div>
      <Facts row={current} columns={fields(spec)} /><IssueDetail spec={spec} row={current} />
    </article></div>
    <details className="pv-more"><summary>表格对照本页 {rows.length} 条记录</summary><RecordTable rows={rows} spec={spec} onSelect={setSelected} onNavigate={onNavigate} /></details>
  </div>;
}

function IssueDetail({ spec, row }: { spec: Data; row: Data }) {
  if (!spec.detail_columns?.length) return null;
  const detail = row.detail;
  return <section className="pv-issue-detail"><h3 className="pv-section-title">发行完整明细</h3>
    {detail == null ? <p className="pv-warning">此方案明细尚未取得，字段状态未知，不按“来源暂无”或零处理。</p>
      : detail.availability === "unavailable" ? <>
        <p className="pv-warning" role="alert">本轮来源暂无可用发行详情。{detail.last_available ? "下方单独保留上次有效明细，仅供参考。" : "尚无已保留的有效明细。"}</p>
        {detail.last_available && <><h3 className="pv-section-title">上次有效发行明细</h3><Facts row={detail.last_available} columns={spec.detail_columns} /></>}
      </> : <Facts row={detail} columns={spec.detail_columns} />}
  </section>;
}
