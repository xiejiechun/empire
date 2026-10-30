import { useMemo, useState } from "react";
import { Input, Select, Tag } from "antd";
import { Data } from "../api";
import { display, OpenDetail, PreviewProps, RecordTable, Security } from "./presentation";
import { compareValue } from "./tableOrder";

type LayoutRow = [string, number, boolean, boolean];
function securityKey(row: Data): string { return row.unified_code || `${row.code}.${row.market}`; }
function layoutRows(spec: Data, reports: Data[]): LayoutRow[] {
  const available = new Set<string>(reports.flatMap(row => Object.keys(row.fields || {})));
  const layouts: LayoutRow[][] = spec.statement_layouts || [];
  const best = [...layouts].sort((a, b) => b.filter(r => available.has(r[0])).length - a.filter(r => available.has(r[0])).length)[0] || [];
  const seen = new Set<string>();
  const ordered = best.filter(([name, , heading]) => {
    if (seen.has(name) || (!heading && !available.has(name))) return false;
    seen.add(name); return true;
  });
  const extras: LayoutRow[] = [...available].filter(name => !seen.has(name)).map(name => [name, 0, false, false]);
  const populated = ordered.filter(([, indent, heading], index) => !heading || ordered.slice(index + 1).some((row, later) =>
    !row[2] && !ordered.slice(index + 1, index + 1 + later).some(previous => previous[2] && previous[1] <= indent)));
  return [...populated, ...(extras.length && populated.length ? [["其他来源科目", 0, true, false] as LayoutRow] : []), ...extras];
}

export function StatementView({ spec, rows, onNavigate }: PreviewProps) {
  if (!spec.hidden) return <div><p className="pv-note">先在报告目录中定位证券和报告期，再打开明细查看该证券全部已归档报告期与完整科目。</p>
    <RecordTable spec={spec} rows={rows} onNavigate={onNavigate} /></div>;
  return <StatementMatrix spec={spec} rows={rows} onNavigate={onNavigate} />;
}

function StatementMatrix({ spec, rows, onNavigate }: PreviewProps) {
  const [chosen, setChosen] = useState("");
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState("all");
  const [sort, setSort] = useState<{ column: string; desc: boolean }>();
  const securities = useMemo(() => [...new Map(rows.map(row => [securityKey(row), row])).values()], [rows]);
  const selected = securities.some(row => securityKey(row) === chosen) ? chosen : securityKey(securities[0] || {});
  const allReports = rows.filter(row => securityKey(row) === selected).sort((a, b) => b.report_date.localeCompare(a.report_date));
  const reports = allReports.filter(row => period === "all" || row.report_date.endsWith(period));
  const layout = layoutRows(spec, reports).filter(([name, , heading]) => !search || !heading && name.includes(search));
  const orderedLayout = !sort ? layout : layout.filter(row => !row[2]).sort((a, b) => {
    if (sort.column === "name") return compareValue(a[0], b[0]) * (sort.desc ? -1 : 1);
    const report = reports.find(row => row.report_date === sort.column);
    const left = report?.fields?.[a[0]]?.value, right = report?.fields?.[b[0]]?.value;
    if ((left == null) !== (right == null)) return left == null ? 1 : -1;
    return left == null ? 0 : compareValue(left, right, "number") * (sort.desc ? -1 : 1);
  });
  function toggle(column: string) { setSort(s => s?.column === column ? s.desc ? undefined : { column, desc: true } : { column, desc: false }); }
  const duplicateDates = new Set(reports.map(row => row.report_date)).size !== reports.length;
  const first = reports[0] || allReports[0] || {};
  return <div className="pv-statement">
    <div className="pv-tool-row">
      <Select aria-label="当前页财报证券" value={selected} style={{ minWidth: 220 }} onChange={setChosen}
        options={securities.map(row => ({ value: securityKey(row), label: `${row.name || ""} ${securityKey(row)}` }))} />
      <Select aria-label="报告期类型" value={period} onChange={setPeriod} style={{ minWidth: 150 }}
        options={[{ value: "all", label: "全部报告期" }, { value: "12-31", label: "年报" }, { value: "06-30", label: "中报" }, { value: "03-31", label: "一季报" }, { value: "09-30", label: "三季报" }]} />
      <Input aria-label="搜索财报科目" placeholder="查找科目，如 营业收入" value={search} onChange={e => setSearch(e.target.value)} allowClear />
    </div>
    {sort && <p className="pv-note">科目按{sort.column === "name" ? "名称" : sort.column + "金额"}{sort.desc ? "降序" : "升序"}排列，空值置后；点击同一表头可切换方向并恢复科目层级。</p>}
    <div className="pv-section-heading"><Security row={first} /><div><Tag>{display(first.period_basis)}</Tag><Tag>{first.currency ? display(first.currency) : "币种未提供"} · 元</Tag><OpenDetail spec={spec} row={first} onNavigate={onNavigate} /></div></div>
    <p className="pv-note">{spec.hidden ? "按已读取的证券历史报告期对照；" : "按当前页报告期对照；"}“—”表示来源空值，“未提供”表示该报告没有此科目。未取得公告日期的财报不能直接作为历史选股信号。</p>
    {duplicateDates ? <div role="alert" className="pv-warning">报告期重复，无法可靠对齐科目，请核查数据。</div> : <div className="pv-matrix-scroll">
      <table className="pv-matrix" aria-label="财报科目对照"><thead><tr><th scope="col" aria-sort={sort?.column === "name" ? sort.desc ? "descending" : "ascending" : "none"}><button type="button" onClick={() => toggle("name")}>科目 / 单位：元 ↕</button></th>{reports.map(row => <th key={row.report_date} scope="col" aria-sort={sort && sort.column === row.report_date ? sort.desc ? "descending" : "ascending" : "none"}><button type="button" onClick={() => toggle(row.report_date)}>{row.report_date} ↕</button><small>{row.announcement_date ? `公告 ${row.announcement_date}` : "公告日期未提供"}</small></th>)}</tr></thead>
        <tbody>{orderedLayout.map(([name, indent, heading, keyMetric]) => <tr key={name} className={heading ? "pv-matrix-group" : keyMetric ? "pv-matrix-key" : ""}>
          <th scope="row" style={{ paddingLeft: 16 + Math.min(indent, 5) * 12 }}>{name.replace(/^\*/, "")}</th>
          {reports.map(row => {
            const exists = Object.hasOwn(row.fields || {}, name), item = row.fields?.[name];
            return <td key={row.report_date} title={item?.resolution ? `来源金额精度：${item.resolution} 元` : undefined}>
              {heading ? "" : !exists ? <span className="pv-unknown">未提供</span> : display(item?.value, { key: name, label: name, kind: "number" })}
            </td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>}
    {!layout.length && <p className="pv-note">当前证券和报告期条件下没有可展示科目。</p>}
    <div className="pv-subtle">当前展示 {reports.length} 个报告期 · {layout.filter(row => !row[2]).length} 个科目。横向滚动可查看其余报告期。</div>
  </div>;
}

