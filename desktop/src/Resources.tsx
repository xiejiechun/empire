import { useEffect, useRef, useState } from "react";
import { Alert, App, Button, Form, InputNumber, Space } from "antd";
import { command, Data, useQuery } from "./api";
import { QueryNotice } from "./shared";

const labels: Record<string, string> = {
  max_parallel_downloads: "同时下载数",
  buffer_budget_bytes: "下载缓冲上限",
};
const mib = (value: number) => (value / 1048576).toLocaleString("zh-CN", { maximumFractionDigits: 1 });

export default function Resources() {
  const q = useQuery("resources.read", {}, 3000);
  const [form] = Form.useForm();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const loaded = useRef(false), version = useRef(0);
  const { message } = App.useApp();
  const fields = q.data?.fields || [];
  const convert = (values: Data) => Object.fromEntries(fields.map((f: Data) => [f.key, values[f.key] / f.scale]));
  useEffect(() => {
    if (q.data && !loaded.current) {
      form.setFieldsValue(convert(q.data.saved));
      loaded.current = true;
    }
  }, [q.data]);
  const live = q.error ? null : q.data?.live;
  return <section aria-label="下载资源设置">
    <QueryNotice query={q} />
    {q.data?.pending_restart && <Alert type="warning" title="配置已保存，正常退出并重新打开软件后生效" />}
    <p>所有采集任务共用这两个上限。通常保持当前设置即可，调高上限不一定会加快采集。</p>
    <Form form={form} layout="vertical" onValuesChange={() => { version.current++; setDirty(true); }}>
      <div className="resource-grid">
        {fields.map((f: Data) => <div key={f.key}>
          <Form.Item name={f.key} label={`${labels[f.key]}（${f.unit}）`} rules={[{ required: true }]}>
            <InputNumber min={f.minimum / f.scale} max={f.maximum / f.scale} precision={0} changeOnWheel={false} />
          </Form.Item>
          <small className="muted">当前生效：{q.data.active?.[f.key] != null ? q.data.active[f.key] / f.scale : "未启用"} · 已保存：{q.data.saved[f.key] / f.scale}</small>
        </div>)}
      </div>
    </Form>
    <p role="status">{live
      ? `正在下载 ${live.active_requests} 个 · 缓冲预留 ${mib(live.buffer_reserved_bytes)} / ${mib(live.buffer_limit_bytes)} MiB · ${live.waiting ? `${live.waiting} 个正在等待下载资源` : "无下载资源排队"}`
      : "下载运行状态暂不可用"}</p>
    <p className="muted">缓冲显示下载器预留额度，并非程序总内存；网站限速和出口等待在任务运行详情查看。单次响应和文件保护限制继续沿用。</p>
    <Space wrap>
      <span>{dirty ? "有未保存修改" : "无未保存修改"}</span>
      <Button disabled={busy || !q.data} onClick={() => {
        form.setFieldsValue(convert(q.data.saved)); version.current++; setDirty(false);
      }}>撤销修改</Button>
      <Button type="primary" loading={busy} disabled={!dirty || !fields.length} onClick={async () => {
        const rev = version.current;
        try {
          const draft = await form.validateFields();
          const values = Object.fromEntries(fields.map((f: Data) => [f.key, draft[f.key] * f.scale]));
          setBusy(true);
          await command("resources.save", { values });
          if (rev === version.current) setDirty(false);
          q.refresh();
          message.success("已保存，正常退出并重新打开软件后生效");
        } catch (e) { message.error(String(e)); }
        finally { setBusy(false); }
      }}>保存设置</Button>
    </Space>
  </section>;
}
