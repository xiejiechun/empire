import Resources from "./Resources";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  InputNumber,
  Modal,
  Pagination,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { command, Data, time, useQuery } from "./api";
import { Details, ObjectTable, QueryNotice } from "./shared";
const titles: Record<string, string> = {
  sites: "站点访问规则",
  exits: "采集出口",
  resources: "共享下载资源",
  identities: "身份管理",
  health: "运行状态",
};
export default function Management({
  page,
  onNavigate,
}: {
  page: string;
  onNavigate?: (page: string) => void;
}) {
  return (
    <div className="page-stack">
      <div className="page-heading-v2">
        <h1>{titles[page]}</h1>
        {page === "exits" && (
          <Button onClick={() => onNavigate?.("sites")}>站点访问规则</Button>
        )}
      </div>
      <section className="workspace-surface fill manager">
        {page === "sites" ? (
          <Sites />
        ) : page === "resources" ? (
          <Resources />
        ) : page === "identities" ? (
          <Identities />
        ) : page === "exits" ? (
          <Exits />
        ) : (
          <Health />
        )}
      </section>
    </div>
  );
}
function Health() {
  const q = useQuery("health.read", {}, 3000);
  return (
    <>
      <QueryNotice query={q} />
      <p>{q.data?.status || q.data?.error}</p>
      <ObjectTable rows={q.data?.plugins || []} />
    </>
  );
}
function Exits() {
  const q = useQuery("exits.read", {}, 5000);
  const rows = q.data?.devices || [];
  const ips = [...new Set<string>(rows.map((r: Data) => r.exit_ip))];
  return (
    <>
      <QueryNotice query={q} />
      <Space>
        <Tag>在线设备 {q.data?.online ?? "未知"}</Tag>
        <Tag>独立出口 {q.data?.online_egresses ?? "未知"}</Tag>
        <Tag>等待分配 {q.data?.waiting ?? "未知"}</Tag>
        <Button onClick={q.refresh}>刷新</Button>
      </Space>
      {q.data?.error && <Alert type="warning" title={q.data.error} />}
      <Table
        rowKey="ip"
        dataSource={ips.map((ip) => ({
          ip,
          devices: rows.filter((r: Data) => r.exit_ip === ip),
        }))}
        pagination={{ pageSize: 20 }}
        expandable={{
          expandedRowRender: (r) => <ObjectTable rows={r.devices} />,
        }}
        columns={[
          { title: "独立出口 IP", dataIndex: "ip" },
          { title: "设备数量", render: (_, r) => r.devices.length },
          {
            title: "当前占用",
            render: (_, r) =>
              r.devices.reduce(
                (n: number, d: Data) => n + Number(d.busy || 0),
                0,
              ),
          },
          {
            title: "请求次数",
            render: (_, r) =>
              r.devices.reduce(
                (n: number, d: Data) => n + Number(d.requests || 0),
                0,
              ),
          },
        ]}
      />
      <p className="muted">
        同IP设备共用出口许可；不同站点独立分配。不展示代理凭据、不主动探测节点。
      </p>
    </>
  );
}
function Sites() {
  const [offset, setOffset] = useState(0),
    [editing, setEditing] = useState<Data>(),
    [busy, setBusy] = useState(false);
  const q = useQuery("sites.list", { offset, limit: 25 }, 5000);
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const mode = Form.useWatch("scaling_mode", form);
  const fields = [
    ["proxy_interval_ms", "每出口 IP 间隔（毫秒）", 100, 60000],
    ["min_interval_ms", "本机直连间隔（毫秒）", 100, 60000],
    ["total_interval_ms", "固定全站间隔（毫秒）", 100, 60000],
    ["max_concurrency", "并发安全阀（0 跟随全局）", 0, 1024],
    ["max_rps", "全站每秒保护（0 不额外限制）", 0, 100],
  ];
  return (
    <>
      <QueryNotice query={q} />
      <Table<Data>
        rowKey="name"
        pagination={false}
        dataSource={q.data?.sites || []}
        columns={[
          { title: "站点", dataIndex: "name" },
          { title: "共享任务数", dataIndex: "task_count" },
          {
            title: "模式",
            dataIndex: "scaling_mode",
            render: (v) => (v === "auto" ? "按出口自动扩展" : "固定限速"),
          },
          { title: "每出口间隔 ms", dataIndex: "proxy_interval_ms" },
          {
            title: "并发上限",
            dataIndex: "max_concurrency",
            render: (v) => (v === 0 ? "跟随全局" : v),
          },
          {
            title: "",
            render: (_, r) => (
              <Button
                onClick={() => {
                  setEditing(r);
                  form.setFieldsValue(
                    Object.fromEntries(
                      ["scaling_mode", ...fields.map((f) => String(f[0]))].map(
                        (key) => [key, r[key]],
                      ),
                    ),
                  );
                }}
              >
                编辑规则
              </Button>
            ),
          },
        ]}
        expandable={{ expandedRowRender: (r) => <Details value={r} /> }}
      />
      <Pagination
        current={offset / 25 + 1}
        pageSize={25}
        showSizeChanger={false}
        total={q.data?.total || 0}
        onChange={(v) => setOffset((v - 1) * 25)}
      />
      <Drawer
        open={!!editing}
        size={480}
        title={`${editing?.name} · 访问规则`}
        onClose={() => setEditing(undefined)}
        footer={
          <Button
            type="primary"
            loading={busy}
            onClick={async () => {
              try {
                const values = await form.validateFields();
                setBusy(true);
                await command("sites.save", { name: editing?.name, values });
                message.success("站点规则已保存");
                setEditing(undefined);
              } catch (e) {
                message.error(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            保存规则
          </Button>
        }
      >
        <Alert type="info" title="同站点任务共享；保存不解除429冷却" />
        <Form form={form} layout="vertical">
          <Form.Item
            name="scaling_mode"
            label="速度模式"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "auto", label: "按健康独立出口自动扩展" },
                { value: "fixed", label: "固定限速" },
              ]}
            />
          </Form.Item>
          {fields.map(([key, label, min, max]) => (
            <Form.Item
              key={key}
              name={String(key)}
              label={String(label)}
              hidden={key === "total_interval_ms" && mode !== "fixed"}
              rules={[{ required: true }]}
            >
              <InputNumber
                min={Number(min)}
                max={Number(max)}
                precision={0}
                changeOnWheel={false}
              />
            </Form.Item>
          ))}
        </Form>
      </Drawer>
    </>
  );
}
function Identities() {
  const catalog = useQuery("identities.catalog", {}, 30000);
  const [platform, setPlatform] = useState(""),
    [offset, setOffset] = useState(0),
    [node, setNode] = useState<Data>();
  useEffect(() => {
    if (!platform && catalog.data?.length) setPlatform(catalog.data[0].id);
  }, [catalog.data]);
  const q = useQuery(
    "identities.read",
    { platform, offset, limit: 25 },
    10000,
    !!platform,
  );
  const { message } = App.useApp();
  return (
    <>
      <QueryNotice query={catalog} />
      <Space>
        <Select
          style={{ width: 220 }}
          value={platform || undefined}
          placeholder="选择平台"
          onChange={(v) => {
            setPlatform(v);
            setOffset(0);
            setNode(undefined);
          }}
          options={(catalog.data || []).map((r: Data) => ({
            value: r.id,
            label: r.name,
          }))}
        />
        <Button onClick={q.refresh}>刷新状态</Button>
        <Tag>协议 {q.data?.protocol_version ?? "未知"}</Tag>
        <Button
          disabled={!q.data || !!q.error}
          onClick={() =>
            Modal.confirm({
              title: `${q.data.running ? "停止" : "启动"}平台身份服务？`,
              content: "影响平台所有共享任务；读取页面不会自行申请或登录。",
              okText: "确认执行",
              cancelText: "取消",
              onOk: async () => {
                try {
                  await command("identity.service", {
                    platform,
                    action: q.data.running ? "stop" : "start",
                  });
                } catch (e) {
                  message.error(String(e));
                  throw e;
                }
              },
            })
          }
        >
          {q.data?.running ? "停止自动身份服务" : "启动自动身份服务"}
        </Button>
      </Space>
      <QueryNotice query={q} />
      {q.data?.warning && <Alert type="warning" title={q.data.warning} />}
      <Descriptions
        size="small"
        items={[
          {
            key: "total",
            label: "保留档案",
            children: q.data?.total ?? "未知",
          },
          {
            key: "current",
            label: "当前操作",
            children: q.data?.current?.length ?? "未知",
          },
          {
            key: "last",
            label: "上一已结束操作",
            children: q.data?.last_run
              ? `${q.data.last_run.status} · ${time(q.data.last_run.finished_at)}`
              : "无保留记录",
          },
        ]}
      />
      <Table<Data>
        rowKey="code"
        dataSource={q.data?.rows || []}
        pagination={false}
        columns={[
          { title: "固定节点", dataIndex: "code" },
          {
            title: "目录",
            dataIndex: "online",
            render: (v) => (v ? "在线" : "离线，档案保留"),
          },
          { title: "申请状态", dataIndex: "registration" },
          {
            title: "上一操作",
            render: (_, r) => r.last_run?.status || "无保留记录",
          },
          { title: "当前操作", render: (_, r) => r.current?.length || 0 },
          {
            title: "",
            render: (_, r) => (
              <Button onClick={() => setNode(r)}>参数与诊断</Button>
            ),
          },
        ]}
      />
      <Pagination
        current={offset / 25 + 1}
        pageSize={25}
        showSizeChanger={false}
        total={q.data?.total || 0}
        onChange={(v) => setOffset((v - 1) * 25)}
      />
      <Drawer
        open={!!node}
        title={`${node?.code} · 身份详情`}
        size={600}
        onClose={() => setNode(undefined)}
      >
        <Details value={node} />
      </Drawer>
    </>
  );
}
