import { useState } from "react";
import { App, Button, Drawer, Modal, Pagination, Table, Tabs } from "antd";
import { command, Data, time, useQuery } from "./api";
import { Details, QueryNotice, Status } from "./shared";
export default function Records({
  project = "",
  runId,
  embedded = false,
}: {
  project?: string;
  runId?: string;
  embedded?: boolean;
}) {
  const [kind, setKind] = useState("collection"),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Data>(),
    [checked, setChecked] = useState<React.Key[]>([]);
  const query = useQuery(
    "records.list",
    { kind, project, offset, limit: 25 },
    5000,
  );
  const detail = useQuery(
    "error.read",
    { ident: selected?.project_id || project, record_id: selected?.id || "" },
    60000,
    kind === "errors" && !!selected,
  );
  const { message } = App.useApp();
  const rows = query.data?.rows || [];
  return (
    <div className={embedded ? "record-embedded" : "page"}>
      {!embedded && (
        <div className="heading">
          <h1>跨任务记录</h1>
          <span className="muted">北京时间 · Redis 有界保留，非永久历史</span>
        </div>
      )}
      <Tabs
        activeKey={kind}
        onChange={(v) => {
          setKind(v);
          setOffset(0);
          setChecked([]);
          setSelected(undefined);
        }}
        items={[
          ["collection", "采集记录"],
          ["archives", "归档记录"],
          ["errors", "错误记录"],
        ].map(([key, label]) => ({ key, label }))}
      />
      <QueryNotice query={query} />
      {kind === "errors" && project && (
        <Button
          disabled={!checked.length}
          onClick={() =>
            Modal.confirm({
              title: `清除 ${checked.length} 条已修复错误？`,
              content:
                "仅在对应问题已修复且验证通过后清理。按确切ID删除，保留并发新增及未处理记录。",
              okText: "确认已修复并清理",
              cancelText: "取消",
              onOk: async () => {
                try {
                  const r = await command("errors.clear", {
                    ident: project,
                    record_ids: checked,
                  });
                  setChecked([]);
                  message.success(`已清理 ${r.removed} 条`);
                } catch (e) {
                  message.error(String(e));
                  throw e;
                }
              },
            })
          }
        >
          清除已修复记录
        </Button>
      )}
      <Table
        size="small"
        rowKey={(r) => r.id || r.run_id}
        dataSource={rows}
        pagination={false}
        rowSelection={
          kind === "errors" && project
            ? { selectedRowKeys: checked, onChange: setChecked }
            : undefined
        }
        scroll={{ x: true }}
        columns={[
          {
            title: "时间",
            render: (_, r) =>
              time(r.created_at || r.started_at || r.finished_at),
          },
          {
            title: "项目",
            render: (_, r) => r.project_id || r.task_id || project,
          },
          {
            title: "结果 / 阶段",
            render: (_, r) => <Status value={r.status || r.stage} />,
          },
          {
            title: "轮次关联",
            render: (_, r) =>
              runId && r.run_id === runId
                ? "当前所选轮次"
                : r.run_id
                  ? "其他轮次"
                  : "未关联记录",
          },
          {
            title: "说明",
            ellipsis: true,
            render: (_, r) => r.message || r.error || r.reason || "—",
          },
          {
            title: "",
            width: 70,
            render: (_, r) => (
              <Button type="link" onClick={() => setSelected(r)}>
                详情
              </Button>
            ),
          },
        ]}
      />
      <Pagination
        size="small"
        showSizeChanger={false}
        current={Math.floor((query.data?.offset ?? offset) / 25) + 1}
        pageSize={25}
        total={query.data?.total || 0}
        onChange={(page) => {
          setOffset((page - 1) * 25);
          setChecked([]);
        }}
      />
      <p className="muted">
        每项目采集/归档各100条，错误300条。Redis重启后可能丢失。
      </p>
      <Drawer
        open={!!selected}
        size={620}
        onClose={() => setSelected(undefined)}
        title="记录详情"
      >
        {kind === "errors" ? (
          <>
            <QueryNotice query={detail} />
            <Details value={detail.data} />
          </>
        ) : (
          <Details value={selected} />
        )}
      </Drawer>
    </div>
  );
}
