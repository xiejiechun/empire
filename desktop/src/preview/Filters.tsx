import { useState } from "react";
import { Alert, Button, Input, Select } from "antd";
import { Data } from "../api";

export function PreviewFilters({ spec, draft, onChange, onSubmit, loading }: {
  spec: Data; draft: Data; onChange: (draft: Data) => void; onSubmit: (filters: Data) => void; loading: boolean;
}) {
  const [error, setError] = useState("");
  const fields: Data[] = spec.filter_specs || [];
  function submit(event: React.FormEvent) {
    event.preventDefault();
    const values = Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, String(v || "").trim()]));
    const missing = fields.find(f => f.required && !values[f.key]);
    if (missing) { setError(`请填写${missing.label}`); return; }
    if (values.security) {
      values.security = values.security.toUpperCase();
      if (!/^\d{6}\.(SH|SZ|BJ)$/.test(values.security)) { setError("请填写完整证券代码，例如 000001.SZ"); return; }
    }
    if (values.start && values.end && values.start > values.end) { setError("开始日期不能晚于结束日期"); return; }
    setError(""); onSubmit(values);
  }
  return <form className="preview-filter-form" onSubmit={submit}>
    <div className="preview-filter-fields">
      {fields.map(field => <label key={field.key} className={field.type === "search" ? "preview-filter-search" : ""}>
        <span>{field.label}{field.required && <em>必填</em>}</span>
        {field.options ? <Select aria-label={field.label} value={draft[field.key] || ""} options={field.options} onChange={value => { setError(""); onChange({ ...draft, [field.key]: value }); }} /> : <Input
          aria-label={field.label} maxLength={200} autoComplete="off" type={["date", "month"].includes(field.type) ? field.type : "text"}
          value={draft[field.key] || ""} placeholder={field.placeholder || "不限"} allowClear={!["date", "month"].includes(field.type)}
          onChange={e => { setError(""); onChange({ ...draft, [field.key]: e.target.value }); }} />}
      </label>)}
      <div className="preview-filter-actions"><Button aria-label="preview-search" type="primary" htmlType="submit" loading={loading}>查询数据</Button><Button onClick={() => { setError(""); onChange(spec.defaults || {}); onSubmit(spec.defaults || {}); }}>重置</Button></div>
    </div>
    {error && <Alert type="warning" title={error} showIcon />}
  </form>;
}
