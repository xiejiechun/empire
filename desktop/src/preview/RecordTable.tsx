import { useContext, useMemo, useState } from "react";
import { Button, Checkbox, Input, Popover, Segmented, Table } from "antd";
import type { Data } from "../api";
import { display, fields, longKinds, numberKinds, OpenDetail, rowIdentity } from "./presentation";
import type { Field, PreviewProps } from "./presentation";
import { orderRows, PreviewOrder } from "./tableOrder";
import type { TableOrder } from "./tableOrder";

export function RecordTable({ rows, spec, onSelect, onNavigate, columns }: PreviewProps & {
  onSelect?: (row: Data) => void; columns?: Field[];
}) {
  const declared = columns || fields(spec);
  const remote = useContext(PreviewOrder);
  const controlled = !!remote && remote.view === spec.id && !spec.hidden;
  const complete = !spec.id || spec.hidden || spec.sort_scope === "complete";
  const sortable = controlled || complete;
  const [localOrder, setLocalOrder] = useState<TableOrder>();
  const [search, setSearch] = useState("");
  const [preferences, setPreferences] = useState({ hidden: [] as string[], compact: true });
  const { hidden, compact } = (controlled && remote?.preferences) || preferences;
  const customize = (next: typeof preferences) => controlled && remote?.customize ? remote.customize(next) : setPreferences(next);
  const order = controlled ? remote?.order : localOrder;
  const change = (next?: TableOrder) => controlled ? remote!.change(next) : setLocalOrder(next);
  const shown = declared.filter(field => !hidden.includes(field.key));
  const data = useMemo(() => complete ? orderRows(rows.filter(row => !search.trim() || declared.some(field =>
    display(row[field.key], field).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))), localOrder,
    Object.fromEntries(declared.map(f => [f.key, f.kind || ""]))) : rows, [rows, localOrder, declared, complete, search]);
  return <div className="pv-table">
    <div className="pv-tool-row" aria-label="表格工具">
      <Popover trigger="click" title="显示列" content={<div style={{ maxHeight: 320, overflowY: "auto", maxWidth: 360 }}>
        <Button size="small" onClick={() => customize({ hidden: [], compact })}>显示全部</Button>
        {declared.map(field => <div key={field.key}><Checkbox checked={!hidden.includes(field.key)}
          disabled={shown.length === 1 && shown[0].key === field.key}
          onChange={event => customize({ compact, hidden: event.target.checked ? hidden.filter(k => k !== field.key) : [...hidden, field.key] })}>
          {field.label}{field.unit ? `（${field.unit}）` : ""}</Checkbox></div>)}
      </div>}><Button size="small">显示列 {shown.length}/{declared.length}</Button></Popover>
      <Segmented size="small" aria-label="表格行距" value={compact ? "紧凑" : "舒适"}
        options={["紧凑", "舒适"]} onChange={value => customize({ hidden, compact: value === "紧凑" })} />
      {complete && <Input size="small" aria-label="查找完整明细" placeholder="查找完整明细" allowClear
        value={search} onChange={event => setSearch(event.target.value)} style={{ width: 190 }} />}
      {sortable && <span className="pv-subtle">{order
        ? `${declared.find(f => f.key === order.field)?.label || order.field} · ${order.direction === "asc" ? "升序" : "降序"}`
        : "点击表头排序"} · {controlled ? "全部筛选结果" : "完整明细集合"} · 空值置后</span>}
      {order && <Button size="small" onClick={() => change(undefined)}>恢复默认顺序</Button>}
      {complete && search && <span className="pv-subtle">匹配 {data.length}/{rows.length} 条</span>}
    </div>
    <Table<Data> size={compact ? "small" : "middle"} dataSource={data} pagination={false}
      rowKey={(row, i) => rowIdentity(row, spec, i)} scroll={{ x: "max-content", y: 520 }}
      onRow={row => ({ onDoubleClick: () => onSelect?.(row) })}
      onChange={(_pagination, _filters, sorter) => {
        const value = Array.isArray(sorter) ? sorter[0] : sorter;
        change(value.order ? { field: String(value.columnKey), direction: value.order === "ascend" ? "asc" : "desc" } : undefined);
      }}
      columns={[
        ...shown.map((field, index) => ({ key: field.key, dataIndex: field.key,
          title: <span>{field.label}{field.unit && <small className="pv-unit">{field.unit}</small>}</span>,
          sorter: sortable ? true : undefined,
          sortOrder: order?.field === field.key ? (order.direction === "asc" ? "ascend" as const : "descend" as const) : null,
          align: numberKinds.has(field.kind || "") ? "right" as const : "left" as const,
          fixed: index === 0 && shown.length > 5 ? "left" as const : undefined,
          width: longKinds.has(field.kind || "") ? 330 : field.kind === "date" ? 132 : 160,
          render: (value: any, row: Data) => <span className={numberKinds.has(field.kind || "") ? "pv-number" : ""}
            title={field.key === "quantity" && row.quantity_scale != null && row.quantity_decimals != null
              ? `来源最小数值刻度约 ${Number(row.quantity_scale) * 10 ** -Number(row.quantity_decimals)} ${field.unit || ""}`
              : display(value, { ...field, format: undefined }) + (field.format === "money" ? " 元" : field.format === "percent" ? "（来源小数）" : "")}>{display(value, field)}</span>,
        })),
        ...(onSelect || spec.detailView ? [{ key: "action", title: "查看", width: onSelect && spec.detailView ? 210 : 116, fixed: "right" as const,
          render: (_: any, row: Data) => <>{onSelect && <Button type="link" size="small" onClick={() => onSelect(row)}>展开记录</Button>}
            <OpenDetail spec={spec} row={row} onNavigate={onNavigate} /></> }] : []),
      ]} />
  </div>;
}
