import { useState } from "react";
import { Button, Tag } from "antd";
import { Data } from "../api";
import { display, Facts, fields, Metric, OpenDetail, PreviewProps, RecordTable, Security } from "./presentation";

export function DirectoryView({ spec, rows, context, onNavigate }: PreviewProps) {
  const isCatalogue = rows.some(row => Object.hasOwn(row, "member_count"));
  if (isCatalogue) return <div className="pv-directory"><div className="pv-card-grid">{rows.map((row, i) => <article className="pv-directory-card" key={row.index_code || row.industry_code || i}>
    <div className="pv-directory-title"><span className="pv-directory-icon">{row.index_code ? "指" : "业"}</span><div><h3>{row.index_name || row.name}</h3><code>{row.index_code || row.industry_code}</code></div></div>
    <div className="pv-metrics"><Metric label="当前成分" value={row.member_count} unit="只" /></div>
    <div className="pv-card-footer"><span className="pv-subtle">{row.source_group || (row.members_available === false ? "来源未提供成分" : "当前目录")}</span><OpenDetail spec={spec} row={row} onNavigate={onNavigate} /></div>
  </article>)}</div><p className="pv-note">成分关系表示当前已归档目录，不能推断早期历史成分。</p></div>;
  const groups = new Map<string, Data[]>();
  for (const row of rows) {
    const group = row.industry_name || row.index_name || display(row.market) || "当前证券";
    groups.set(group, [...groups.get(group) || [], row]);
  }
  return <div className="pv-directory"><div className="pv-group-strip" aria-label="本页分组">{[...groups].map(([name, members]) => <Tag key={name}>{name} · 本页 {members.length}</Tag>)}</div>
    {context?.industry_count != null && <p className="pv-subtle">当前行业目录共 {context.industry_count} 项，下面仅为当前页成员。</p>}
    <RecordTable spec={spec} rows={rows} onNavigate={onNavigate} />
  </div>;
}

export function ThemesView({ spec, rows, context, onNavigate }: PreviewProps) {
  const head = context?.head;
  if (head || spec.id === "details") return <div className="pv-theme-detail">
    {head && <article className="pv-theme-intro"><Tag>题材 {head.theme_id}</Tag><h2>{head.name}</h2><p>{head.brief}</p><div>{head.introduction || "来源未提供完整介绍"}</div></article>}
    <h3 className="pv-section-title">关联证券与入选理由</h3>
    <div className="pv-reason-list">{rows.map((row, i) => <article className="pv-theme-reason" key={row.relation_id || i}>
      <div className="pv-section-heading"><Security row={row} /><Tag>{row.category_name || "未分类"}</Tag></div><p>{row.reason || "来源未提供理由"}</p>
      <div className="pv-subtle">首次上架：{display(row.first_shelved_at)} · 来源更新：{display(row.updated_at)}{row.is_hot ? " · 热门" : ""}{row.is_new ? " · 新增" : ""}</div>
    </article>)}</div>
  </div>;
  return <div className="pv-theme-grid">{rows.map((row, i) => <article className="pv-theme-card" key={row.theme_id || i}>
    <div className="pv-card-footer"><span className="pv-rank">#{row.rank_no ?? "—"}</span>{row.new_flag ? <Tag color="cyan">新增题材</Tag> : <span className="pv-subtle">题材 {row.theme_id}</span>}</div>
    <h3>{row.name}</h3><div className="pv-metrics"><Metric label="涨跌幅" value={row.change_rate} unit="%" /><Metric label="涨停家数" value={row.limit_up_count} unit="家" /></div>
    <div className="pv-card-footer"><span className="pv-subtle">热度 {display(row.hot_score)}{row.parent_id ? ` · 上级 ${row.parent_id}` : ""}</span>
      {spec.detailView ? <OpenDetail spec={spec} row={row} onNavigate={onNavigate} /> : <Button type="link" size="small" onClick={() => onNavigate?.("details", { theme_id: String(row.theme_id) })}>查看关联证券 →</Button>}</div>
  </article>)}</div>;
}

export function PoolView({ spec, rows, context, onNavigate }: PreviewProps) {
  const [selected, setSelected] = useState<Data>();
  const current = selected && rows.includes(selected) ? selected : undefined;
  const head = context?.head || {};
  const largest = rows.reduce<Data | undefined>((best, row) => row.change_rate != null && (!best || Number(row.change_rate) > Number(best.change_rate)) ? row : best, undefined);
  return <div className="pv-pool"><div className="pv-metrics"><Metric label="本页证券" value={rows.length} unit="只" />
    {(head.source_total ?? context?.source_total) != null && <Metric label="来源当日总数" value={head.source_total ?? context?.source_total} unit="只" />}
    {largest && <Metric label={`本页最高涨幅 · ${largest.name || largest.unified_code}`} value={largest.change_rate} unit="%" />}
  </div>
    {(context?.snapshot_at || context?.at) && <p className="pv-note">盘中快照时间：{display(context.snapshot_at || context.at)}</p>}
    <RecordTable spec={spec} rows={rows} onSelect={setSelected} onNavigate={onNavigate} />
    {current && <article className="pv-record-detail"><div className="pv-section-heading"><Security row={current} /><Button onClick={() => setSelected(undefined)} size="small">收起</Button></div><Facts row={current} columns={fields(spec)} /></article>}
    <p className="pv-note">本页统计只描述当前页，不代表全市场统计。盘中快照与日终数据分别查看。</p>
  </div>;
}

export function RulesView({ spec, rows, onNavigate }: PreviewProps) {
  if (spec.hidden) return <div className="pv-citations">{rows.map((row, i) => <article className="pv-rule-citation" key={i}>
    <Tag>{row.issuer}</Tag><h2>{row.title}</h2><p className="pv-subtle">公布日期 {display(row.published_date)} · 条款 {display(row.clause_key)}</p>
    <blockquote>{row.excerpt}</blockquote><div className="pv-subtle">来源地址</div><p className="pv-source-url">{row.source_url}</p>
  </article>)}</div>;
  return <div className="pv-rules">{rows.map((row, i) => <article className="pv-rule-card" key={row.record_key || i}>
    <div className="pv-section-heading"><div><Tag>{display(row.market)}</Tag><Tag>{display(row.board)}</Tag></div><span className="pv-subtle">{display(row.condition_key)}</span></div>
    <h3>{display(row.parameter_key)}</h3>
    {row.number_value != null && <div className="pv-rule-value">{display(row.number_value, { key: "number_value", label: "数值", kind: "number" })}<small>{display(row.unit)}</small></div>}
    {row.start_time && <div className="pv-session-range">{row.start_time} — {row.end_time || "未提供"}<small>北京时间</small></div>}
    <p className="pv-rule-text">{row.text_value || (row.number_value == null && !row.start_time ? "来源未提供参数值" : "")}</p>
    <div className="pv-card-footer"><span className="pv-subtle">生效 {row.effective_start} → {row.effective_end || "结束日期未提供"}</span><OpenDetail spec={spec} row={row} onNavigate={onNavigate} /></div>
  </article>)}</div>;
}

export function ReasonView({ spec, rows }: PreviewProps) {
  return <div className="pv-reason-list">{rows.map((row, i) => <article className="pv-theme-reason" key={i}>
    <div className="pv-section-heading"><Security row={row} /><Tag>{row.trade_date}</Tag></div>
    <p>{row.reason_text || "来源未提供原因正文"}</p><Facts row={row} columns={fields(spec).filter(f => f.key !== "reason_text")} />
  </article>)}</div>;
}
