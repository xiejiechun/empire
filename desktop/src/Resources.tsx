import { useEffect, useRef, useState } from "react";
import { Alert, App, Button, Form, InputNumber, Space } from "antd";
import { command, Data, useQuery } from "./api";
import { QueryNotice } from "./shared";

const labels: Record<string, string> = {
  max_parallel_downloads: "同时下载数",
  buffer_budget_bytes: "下载临时内存上限",
};
const mib = (value: number) => (value / 1048576).toLocaleString("zh-CN", { maximumFractionDigits: 1 });
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;

export default function Resources() {
  const q = useQuery("resources.read", {}, 3000);
  const processing = useQuery("health.read", {}, 3000);
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
  const plugins: Data[] = processing.error ? [] : processing.data?.plugins || [];
  const compute = plugins.find(p => p.id === "dataset.astock" && ["RUNNING", "DEGRADED"].includes(p.state))?.health?.compute;
  const archive = plugins.find(p => p.id === "pipeline.archive" && ["RUNNING", "DEGRADED"].includes(p.state))?.health;
  return <section aria-label="下载资源设置">
    <QueryNotice query={q} />
    <QueryNotice query={processing} />
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
    {live?.effective_download_window != null && <p role="status">
      当前有效下载窗口：{live.effective_download_window} · 等待准入：{live.download_admission_waiting}
      {live.download_feedback_reason ? ` · ${live.download_feedback_reason}，暂缓新增下载` : ""}
    </p>}
    <p role="status">{isCount(compute?.active) && isCount(compute?.waiting)
      ? `后台解析与校验：正在处理 ${compute.active} 项 · 等待 ${compute.waiting} 项`
      : "后台解析状态暂不可用"}</p>
    <p role="status">{isCount(archive?.ready_pending) && isCount(archive?.staging_batches)
      ? `归档最近扫描：可处理 ${archive.ready_pending} 条 · 待补齐 ${archive.staging_batches} 批${archive.blocked ? " · 归档已阻断，请查看错误" : archive.blocked_projects?.length ? ` · 隔离项目 ${archive.blocked_projects.length} 个` : ""}${typeof archive.queue_sample_age_seconds !== "number" || !Number.isFinite(archive.queue_sample_age_seconds) ? " · 扫描时间未知，仅供参考" : archive.queue_sample_age_seconds > 3 ? ` · ${Math.ceil(archive.queue_sample_age_seconds)} 秒前，仅供参考` : ""}`
      : "归档扫描状态尚未就绪"}</p>
    <p className="muted">按实际响应大小申请额度，不是 Redis 或程序总内存。多个大响应耗尽预算时会明确报错，可降低并发后恢复；网站限速和出口等待在任务详情查看。</p>
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
