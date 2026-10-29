import { useState } from "react";
import { Button, Drawer, Pagination, Space, Table, Tag } from "antd";
import { Data, label, time, useQuery } from "./api";
import { Details, QueryNotice, Status } from "./shared";
const names: Record<string, string> = {
  collection: "采集",
  archives: "归档",
  errors: "错误",
};
export default function Events({
  project,
  runId,
}: {
  project: string;
  runId?: string;
}) {
  const [stage, setStage] = useState(""),
    [unlinked, setUnlinked] = useState(false),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Data>();
  const archives = stage === "archives";
  const q = useQuery(
    "run.events",
    { ident: project, run_id: archives ? "" : runId || "", stage, unlinked: archives ? false : unlinked, offset, limit: 15 },
    5000,
    !!runId || unlinked || archives,
  );
  const detail = useQuery(
    "error.read",
    { ident: project, record_id: selected?.record_id || "" },
    60000,
    selected?.stage === "errors",
  );
  return (
    <>
      <QueryNotice query={q} />
      <div className="journal-filters">
        {["", "collection", "archives", "errors"].map((key) => (
          <Button
            size="small"
            key={key}
            type={stage === key ? "primary" : "text"}
            onClick={() => {
              setStage(key);
              setUnlinked(false);
              setOffset(0);
            }}
          >
            {names[key] || "全部事件"}
          </Button>
        ))}
        {!archives && <Button
          size="small"
          type={unlinked ? "primary" : "text"}
          onClick={() => {
            setUnlinked(!unlinked);
            setOffset(0);
          }}
        >
          {unlinked
            ? "返回所选轮次"
            : `未关联记录 ${q.data?.unlinked_count ?? "—"}`}
        </Button>}
        <span className="muted">北京时间 · 按实际发生顺序</span>
      </div>
      {archives && <p className="journal-note">本任务归档记录 · 包含各轮次，按归档实际发生时间展示；归档批次编号与采集轮次编号不同。</p>}
      <Table<Data>
        className="journal-events"
        size="small"
        rowKey="id"
        dataSource={runId || unlinked || archives ? q.data?.rows || [] : []}
        pagination={false}
        columns={[
          {
            title: "时间",
            width: archives ? 180 : 90,
            render: (_, r) => (
              <span title={time(r.timestamp)}>
                {archives ? time(r.timestamp) : time(r.timestamp).slice(-8)}
              </span>
            ),
          },
          {
            title: "阶段",
            dataIndex: "stage",
            width: 70,
            render: (v) => <Tag>{names[v]}</Tag>,
          },
          {
            title: "结果",
            dataIndex: "status",
            width: 110,
            render: (v) => <Status value={v} />,
          },
          {
            title: "说明",
            render: (_, r) => r.message || (archives && r.detail?.processed_count != null
              ? `已处理 ${r.detail.processed_count} 条${r.detail.written_count != null ? `，实际写入 ${r.detail.written_count} 条` : ""}`
              : label(r.status)),
            ellipsis: true,
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
        locale={{
          emptyText: archives ? "本任务暂无保留的归档记录；盘中 Redis 快照不产生 MySQL 归档记录" : unlinked
            ? "没有保留的未关联记录"
            : "该轮暂无可关联事件；其他记录可在“未关联记录”中查看",
        }}
      />
      <Pagination
        hideOnSinglePage
        size="small"
        showSizeChanger={false}
        current={Math.floor((q.data?.offset ?? offset) / 15) + 1}
        pageSize={15}
        total={q.data?.total || 0}
        onChange={(v) => setOffset((v - 1) * 15)}
      />
      <p className="journal-note">
        {archives ? "每项目保留最近100条归档记录；Redis服务重启后记录会丢失，已入库业务数据不受影响。" : "缺少轮次标识的历史不按时间猜测关联；这里只展示仍在保留范围内的记录。"}
      </p>
      <Drawer
        title="事件详情"
        open={!!selected}
        size={600}
        onClose={() => setSelected(undefined)}
      >
        {selected?.stage === "errors" ? (
          <>
            <QueryNotice query={detail} />
            <Details value={detail.data} />
          </>
        ) : (
          <Details value={selected?.detail} />
        )}
      </Drawer>
    </>
  );
}
