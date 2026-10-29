import { useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
  Space,
  Switch,
} from "antd";
import { command, Data } from "./api";
export default function Plan({
  job,
  onClose,
  drafts,
}: {
  job: Data;
  onClose: () => void;
  drafts: Record<string, Data>;
}) {
  const [form] = Form.useForm(),
    [busy, setBusy] = useState(false);
  const version = useRef(0),
    base = useRef(job.policy);
  const { message } = App.useApp();
  const mode = Form.useWatch("mode", form);
  const [dirty, setDirty] = useState(!!drafts[job.id]);
  useEffect(() => {
    form.setFieldsValue(drafts[job.id] || job.policy);
  }, [job.id]);
  const save = async () => {
    try {
      const values = await form.validateFields();
      const rev = version.current;
      setBusy(true);
      const result = await command("collection.policy.save", {
        ident: job.id,
        policy: values,
      });
      base.current = values;
      if (version.current === rev) {
        delete drafts[job.id];
        setDirty(false);
      }
      message.success(result.message);
    } catch (e) {
      message.error(String(e));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!busy) void save();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  return (
    <Drawer
      open
      title={`${job.name} · 执行计划`}
      size={470}
      onClose={onClose}
      footer={
        <Space>
          <span>{dirty ? "未保存草稿" : "已保存"}</span>
          <Button
            disabled={busy}
            onClick={() => {
              version.current++;
              form.setFieldsValue(base.current);
              delete drafts[job.id];
              setDirty(false);
            }}
          >
            撤销
          </Button>
          <Button
            type="primary"
            loading={busy}
            disabled={!dirty}
            onClick={save}
          >
            保存计划
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        title="安排保存后生效；网络与重试从下一轮生效"
        description="关闭面板保留本次会话草稿，后台刷新不会覆盖正在编辑的内容。"
      />
      <Form
        form={form}
        layout="vertical"
        onValuesChange={(_, all) => {
          version.current++;
          drafts[job.id] = all;
          setDirty(true);
        }}
        style={{ marginTop: 20 }}
      >
        <Form.Item name="enabled" label="启用任务" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="mode" label="执行方式" rules={[{ required: true }]}>
          <Segmented
            options={[
              { value: "manual", label: "仅手动" },
              { value: "interval", label: "固定间隔" },
              { value: "daily", label: "每天定时" },
            ]}
          />
        </Form.Item>
        <Form.Item
          name="interval_seconds"
          label="每轮结束后等待（秒）"
          hidden={mode !== "interval"}
          rules={[{ required: true }]}
        >
          <InputNumber
            min={1}
            max={2592000}
            precision={0}
            changeOnWheel={false}
          />
        </Form.Item>
        <Form.Item
          name="daily_time"
          label="每天执行时间 · 北京时间"
          hidden={mode !== "daily"}
          rules={[{ required: true }]}
        >
          <Input type="time" />
        </Form.Item>
        <Form.Item
          name="request_retries"
          label="请求失败重试次数"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} max={100} precision={0} changeOnWheel={false} />
        </Form.Item>
        <Form.Item
          name="use_proxy"
          label="优先使用代理"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="proxy_fallback"
          label="代理不可用时允许回退直连"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
