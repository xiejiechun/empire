import { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Popover, Select, Skeleton, Space, Tag } from "antd";
import { Data, useQuery } from "./api";
import { QueryNotice } from "./shared";
import { PreviewContent } from "./preview/PreviewContent";
import { PreviewFilters } from "./preview/Filters";
import { usePreviewRead } from "./preview/usePreviewRead";
import { PreviewOrder } from "./preview/tableOrder";
import type { TableOrder, TablePreferences } from "./preview/tableOrder";
import "./preview/workspace.css";

type Selection = { view: string; filters: Data; draft: Data; cursors: any[]; revision: number; order?: TableOrder };
const selection = (spec: Data, filters = spec.defaults || {}): Selection => ({
  view: spec.id, filters, draft: filters, cursors: [null], revision: 0,
});

export default function DataPreview({ project }: { project: string }) {
  const catalog = useQuery("preview.catalog", { ident: project }, 60000);
  if (catalog.error && !catalog.data) return <Alert showIcon type="error" title="预览目录读取失败" description={catalog.error} action={<Button onClick={catalog.refresh}>重试</Button>} />;
  if (!catalog.data) return <div className="project-preview-loading"><QueryNotice query={catalog} /><Skeleton active paragraph={{ rows: 5 }} /></div>;
  if (!catalog.data.length) return <Empty description="此采集项目尚未登记预览界面" />;
  return <PreviewWorkspace key={project} project={project} catalog={catalog.data} />;
}

function PreviewWorkspace({ project, catalog }: { project: string; catalog: Data[] }) {
  const visible = catalog.filter(v => !v.hidden);
  const [current, setCurrent] = useState<Selection>(() => selection(visible[0]));
  const savedViews = useRef<Record<string, Selection>>({});
  const [trail, setTrail] = useState<Selection[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [tables, setTables] = useState<Record<string, TablePreferences>>({});
  useEffect(() => {
    if (!expanded) return;
    const exit = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector(".ant-drawer-open")) setExpanded(false);
    };
    window.addEventListener("keydown", exit);
    return () => window.removeEventListener("keydown", exit);
  }, [expanded]);
  const spec = catalog.find(v => v.id === current.view)!;
  const query = usePreviewRead(project, current.view, current.filters, current.cursors.at(-1), current.revision, current.order);
  const rows = query.data?.rows || [];
  const nextCursor = query.data?.next;
  const pendingDraft = JSON.stringify(current.draft) !== JSON.stringify(current.filters);
  function submit(filters: Data) {
    setCurrent(s => ({ ...s, filters, draft: filters, cursors: [null], revision: s.revision + 1 }));
  }
  function navigate(view: string, filters: Data) {
    const target = catalog.find(v => v.id === view);
    if (!target) return;
    setTrail(t => [...t, current]);
    setCurrent(selection(target, { ...target.defaults, ...filters }));
  }
  return <section className={`project-preview${expanded ? " is-expanded" : ""}`} data-testid="project-preview" data-project={project} data-view={spec.id}>
    <header className="preview-workspace-heading">
      <div><h3>{spec.title}</h3><p>{spec.description}</p></div>
      <Space wrap>
        <Popover trigger="click" placement="bottomRight" title="数据口径与阅读说明" content={<div className="preview-reading-notes">{(spec.notes || []).map((note: string) => <p key={note}>{note}</p>)}<p>{query.data?.notice || "查询只读取已有数据；无记录不代表该范围已完成采集。"}</p></div>}><Button>阅读说明</Button></Popover>
        {trail.length > 0 && <Button aria-label="preview-back" onClick={() => { setCurrent(trail[trail.length - 1]); setTrail(trail.slice(0, -1)); }}>返回{catalog.find(v => v.id === trail[trail.length - 1].view)?.title}</Button>}
        <Button onClick={() => setExpanded(!expanded)} aria-pressed={expanded}>{expanded ? "收起预览" : "展开预览"}</Button>
      </Space>
    </header>
    {visible.length > 1 && !spec.hidden && <div className="preview-view-tabs" role="tablist" aria-label="数据栏目">{visible.map(v => <Button key={v.id} role="tab" aria-selected={current.view === v.id} type={current.view === v.id ? "primary" : "default"} onClick={() => {
      savedViews.current[current.view] = current;
      setTrail([]); setCurrent(savedViews.current[v.id] || selection(v));
    }}>{v.title}</Button>)}</div>}
    {!spec.hidden && <PreviewFilters key={spec.id} spec={spec} draft={current.draft} onChange={draft => setCurrent(s => ({ ...s, draft }))} onSubmit={submit} loading={query.loading} />}
    {spec.sort_scope === "filtered" && <div className="pv-tool-row" aria-label="全部筛选结果排序">
      <span>排序</span><Select aria-label="排序字段" value={current.order?.field || ""} style={{ minWidth: 210 }}
        options={[{ value: "", label: "默认顺序" }, ...spec.columns.map((field: Data) => ({ value: field.key, label: field.label }))]}
        onChange={field => setCurrent(s => ({ ...s, order: field ? { field, direction: s.order?.direction || "asc" } : undefined, cursors: [null] }))} />
      <Select aria-label="排序方向" value={current.order?.direction || "asc"} disabled={!current.order} style={{ width: 100 }}
        options={[{ value: "asc", label: "升序" }, { value: "desc", label: "降序" }]}
        onChange={direction => setCurrent(s => ({ ...s, order: s.order ? { ...s.order, direction } : undefined, cursors: [null] }))} />
      <span className="pv-subtle">对全部筛选结果排序后分页；空值置后</span>
    </div>}
    <div className="preview-result-context">
      <div><Tag color={query.data?.storage?.includes("Redis") ? "orange" : "blue"}>{query.data?.storage || "只读查询"}</Tag>
        {Object.entries(current.filters).filter(([k,v]) => v && !["record_key", "plan_id"].includes(k)).map(([k,v]) => <span className="preview-applied" key={k}>{spec.filter_specs?.find((f: Data) => f.key === k)?.label || "筛选条件"}：{spec.filter_specs?.find((f: Data) => f.key === k)?.options?.find((o: Data) => o.value === v)?.label || String(v)}</span>)}
        {pendingDraft && <Tag color="gold">筛选已修改，查询后生效</Tag>}
      </div>
      <span className="muted">{query.loading ? "正在读取…" : query.stamp ? `读取于 ${new Date(query.stamp).toLocaleTimeString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" })}` : "等待查询"}</span>
    </div>
    {query.error && <Alert showIcon type="error" title="本次查询未成功" description={query.error} action={<Button onClick={() => setCurrent(s => ({ ...s, revision: s.revision + 1 }))}>重试</Button>} />}
    {query.data?.message && !query.data?.required && <Alert showIcon type="info" title={query.data.message} />}
    <PreviewOrder.Provider value={spec.sort_scope === "filtered" ? {
      view: current.view, order: current.order,
      change: order => setCurrent(s => ({ ...s, order, cursors: [null], revision: s.revision + 1 })),
      preferences: tables[current.view],
      customize: preferences => setTables(s => ({ ...s, [current.view]: preferences })),
    } : null}>
    <div className="preview-result-body" aria-busy={query.loading}>
      {query.loading ? <Skeleton active paragraph={{ rows: 6 }} /> : query.error ? null : query.data?.required ? <Empty description={query.data.message} image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <PreviewContent key={current.view + JSON.stringify(current.filters) + JSON.stringify(current.cursors)} spec={spec} rows={rows} context={{ ...query.data?.context, filters: current.filters }} onNavigate={navigate} />}
    </div>
    </PreviewOrder.Provider>
    <footer className="preview-workspace-footer">
      <span>{query.loading ? "读取中" : query.error ? "查询失败" : query.data?.required ? "等待填写查询条件" : `本页 ${rows.length} 条`} · 第 {current.cursors.length} 页{query.data?.total != null && ` · 共 ${query.data.total} 条`}</span>
      <Space><Button aria-label="preview-first" disabled={query.loading || current.cursors.length === 1} onClick={() => setCurrent(s => ({ ...s, cursors: [null] }))}>第一页</Button>
        <Button aria-label="preview-previous" disabled={query.loading || current.cursors.length === 1} onClick={() => setCurrent(s => ({ ...s, cursors: s.cursors.slice(0, -1) }))}>上一页</Button>
        <Button aria-label="preview-next" disabled={query.loading || !!query.error || nextCursor == null} onClick={() => setCurrent(s => ({ ...s, cursors: [...s.cursors, nextCursor] }))}>下一页</Button></Space>
    </footer>
  </section>;
}
