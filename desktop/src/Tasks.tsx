import { useEffect, useRef, useState } from "react";
import {
  App,
  Badge,
  Button,
  Descriptions,
  Dropdown,
  Empty,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Tabs,
  Tree,
} from "antd";
import { command, Data, label, time, useQuery } from "./api";
import { Details, QueryNotice, Status } from "./shared";
import Plan from "./Plan";
import DataPreview from "./DataPreview";
import RunJournal from "./RunJournal";
import CollectionRules from "./CollectionRules";
import { progressPercent } from "./progress";
export default function Tasks({
  active,
  archived,
  onPage,
}: {
  active: boolean;
  archived: boolean;
  onPage: (p: string) => void;
}) {
  const [search, setSearch] = useState(""),
    [category, setCategory] = useState<string>(),
    [state, setState] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState(""),
    [checked, setChecked] = useState<React.Key[]>([]),
    [batch, setBatch] = useState(false),
    [editing, setEditing] = useState(false),
    [tab, setTab] = useState("runs"),
    [expanded, setExpanded] = useState<React.Key[]>([]);
  const drafts = useRef<Record<string, Data>>({});
  const { message } = App.useApp();
  const searchRef = useRef<any>(null);
  const list = useQuery(
    "tasks.list",
    {
      query: search,
      category: category || "",
      status: state,
      archived,
      offset,
      limit: 100,
    },
    5000,
    active,
  );
  const detail = useQuery(
    "task.read",
    { ident: selected },
    2000,
    active && !!selected,
  );
  const rules = useQuery(
    "collection.rules.read",
    { ident: selected },
    60000,
    active && !!selected && tab === "rules",
  );
  const rows = list.data?.rows || [];
  const job = detail.data;
  useEffect(() => {
    setOffset(0);
    setChecked([]);
  }, [search, category, state, archived]);
  useEffect(() => {
    if (list.data && !rows.some((r: Data) => r.id === selected)) {
      setSelected(rows[0]?.id || "");
      setExpanded(rows[0] ? ["platform:" + rows[0].source] : []);
      setEditing(false);
    }
  }, [list.data]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (active && e.ctrlKey && e.key === "f") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [active]);
  const act = (
    operation: string,
    params: Data,
    title: string,
    description: string,
  ) =>
    Modal.confirm({
      title,
      content: description,
      okText: "确认执行",
      cancelText: "取消",
      onOk: async () => {
        try {
          const result = await command(operation, params);
          if (result?.results)
            Modal.info({
              title: "批量操作结果",
              width: 650,
              content: <Details value={result} />,
            });
          else message.success(result?.message || "操作已完成");
        } catch (e) {
          message.error(String(e));
          throw e;
        }
      },
    });
  const tree = [...new Set<string>(rows.map((r: Data) => r.source))].map(
    (source) => ({
      key: "platform:" + source,
      selectable: false,
      title: (
        <span className="platform-tree-title">
          <strong>
            {rows.find((r: Data) => r.source === source)?.source_name}
          </strong>
          <small>{rows.filter((r: Data) => r.source === source).length}</small>
        </span>
      ),
      children: rows
        .filter((r: Data) => r.source === source)
        .map((r: Data) => ({
          key: r.id,
          title: (
            <span className="task-tree-title task-leaf">
              <span title={`${r.name} · ${r.id}`}>{r.name}</span>
              <Badge
                status={
                  r.state === "running"
                    ? "processing"
                    : r.state === "error"
                      ? "error"
                      : r.state === "complete"
                        ? "success"
                        : "default"
                }
                title={label(r.state)}
              />
              {r.state === "running" && <small className="compact-task-progress" title={`采集进度 · ${r.progress?.unit_name || "完整单元"}；仍须等待本轮完成确认`}>{progressPercent(r.progress) == null ? (r.progress?.status === "awaiting_archive" ? "待归档" : "采集中") : `${r.progress?.unit_name?.includes("当前批") ? "本批 " : ""}${progressPercent(r.progress)}%`}</small>}
            </span>
          ),
        })),
    }),
  );
  return (
    <div className="page-stack">
      <div className="page-heading-v2">
        <div className="heading-title">
          <div>
            <h1>
              {archived ? "已归档任务" : "采集任务"}{" "}
              <span className="title-count">{list.data?.total ?? "—"}</span>
            </h1>
            <span className="muted">查看进度、处理异常与管理执行计划</span>
          </div>
        </div>
        <Space>
          <Button
            onClick={() => {
              setBatch(!batch);
              setChecked([]);
            }}
          >
            {batch ? "结束批量选择" : "批量操作"}
          </Button>
          <Button onClick={() => onPage("records")}>跨任务记录</Button>
        </Space>
      </div>
      <QueryNotice query={list} />
      <div className="task-directory-workspace fill">
        <aside className="task-directory">
          <div className="directory-tools">
            <Input
              ref={searchRef}
              aria-label="搜索采集项"
              allowClear
              placeholder="搜索平台、名称或任务 ID"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Select
              aria-label="业务分类"
              allowClear
              placeholder="全部业务分类"
              value={category}
              onChange={setCategory}
              options={(list.data?.categories || []).map((value: string) => ({
                value,
                label: value,
              }))}
            />
            <Select
              aria-label="任务状态"
              value={state}
              onChange={setState}
              options={[
                "",
                "running",
                "error",
                "source_gap",
                "disabled",
                "complete",
                "paused",
                "idle",
              ].map((value) => ({
                value,
                label: value ? label(value) : "全部状态",
              }))}
            />
            {batch && (
              <Space wrap>
                <span>已选 {checked.length}</span>
                {["start", "stop"].map((operation) => (
                  <Button
                    key={operation}
                    size="small"
                    disabled={!checked.length || archived}
                    onClick={() =>
                      act(
                        "collection.batch",
                        { operation, identifiers: checked },
                        operation === "start"
                          ? "批量启动所选任务？"
                          : "批量暂停所选任务？",
                        operation === "start"
                          ? "启用任务，使用已保存配置；运行中任务跳过，草稿保留。"
                          : "停止当前采集并停用后续计划，保留断点与已归档数据。",
                      )
                    }
                  >
                    {operation === "start" ? "启动" : "暂停"}
                  </Button>
                ))}
              </Space>
            )}
          </div>
          <div className="directory-caption">
            <span>平台 / 采集项</span>
            <span>{rows.length} 项</span>
          </div>
          <div className="directory-tree">
            {rows.length ? (
              <Tree
                showLine={{ showLeafIcon: false }}
                blockNode
                checkable={batch}
                checkedKeys={checked}
                onCheck={(keys) =>
                  setChecked(
                    (Array.isArray(keys) ? keys : keys.checked).filter(
                      (k) => !String(k).startsWith("platform:"),
                    ),
                  )
                }
                expandedKeys={search ? tree.map((t) => t.key) : expanded}
                onExpand={setExpanded}
                key={`${search}:${offset}:${category}:${archived}`}
                selectedKeys={[selected]}
                onSelect={(keys) => {
                  if (keys.length) {
                    setSelected(String(keys[0]));
                    setEditing(false);
                  }
                }}
                treeData={tree}
              />
            ) : (
              <Empty
                description={list.error ? "暂不可用" : "没有符合条件的任务"}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            )}
          </div>
          <Pagination
            hideOnSinglePage
            simple
            size="small"
            current={Math.floor(offset / 100) + 1}
            pageSize={100}
            total={list.data?.total || 0}
            onChange={(page) => setOffset((page - 1) * 100)}
          />
        </aside>
        <section className="workspace-surface task-focus">
          <QueryNotice query={detail} />
          {job && selected === job.id ? (
            <>
              <div className="focused-task-heading focus-heading">
                <div>
                  <span className="muted">
                    {job.source_name} / {job.category}
                  </span>
                  <h2>
                    {job.name}{" "}
                    <Status
                      value={
                        job.active
                          ? job.progress?.status || "running"
                          : job.last_status
                      }
                    />
                  </h2>
                  <span
                    className="muted"
                    title={
                      job.next_due
                        ? `下次执行：${time(job.next_due)}`
                        : "未安排"
                    }
                  >
                    {!job.policy.enabled
                      ? "已停用计划"
                      : job.policy.mode === "daily"
                        ? `每天 ${job.policy.daily_time} · 北京时间`
                        : job.policy.mode === "interval"
                          ? `每轮结束后等待 ${job.policy.interval_seconds} 秒`
                          : "仅手动执行"}
                  </span>
                </div>
                <Space wrap>
                  {archived ? (
                    <Button
                      type="primary"
                      onClick={() =>
                        act(
                          "collection.archive",
                          { ident: job.id, archived: false },
                          "还原任务？",
                          "保留原配置和启停状态，不强制启动已停用任务。",
                        )
                      }
                    >
                      还原任务
                    </Button>
                  ) : (
                    <>
                      <Button
                        type="primary"
                        disabled={!job.policy.enabled || !!job.active}
                        onClick={() =>
                          act(
                            "collection.run",
                            { ident: job.id, fresh: false },
                            "按已保存配置执行？",
                            "沿用正式断点与来源恢复规则，未保存草稿不参与本次执行。",
                          )
                        }
                      >
                        {job.active
                          ? "任务运行中"
                          : job.last_status === "source_gap"
                            ? "检查更新"
                            : "立即采集"}
                      </Button>
                      <Button onClick={() => setEditing(true)}>
                        执行计划{drafts.current[job.id] ? " · 草稿" : ""}
                      </Button>
                      <Dropdown
                        menu={{
                          items: [
                            {
                              key: "fresh",
                              label: "重新采集",
                              disabled: !!job.active || !job.policy.enabled,
                            },
                            { key: "pause", label: "暂停并停用计划" },
                            { key: "archive", label: "归档任务" },
                          ],
                          onClick: ({ key }) =>
                            act(
                              key === "archive"
                                ? "collection.archive"
                                : key === "pause"
                                  ? "collection.pause"
                                  : "collection.run",
                              {
                                ident: job.id,
                                ...(key === "archive"
                                  ? { archived: true }
                                  : key === "fresh"
                                    ? { fresh: true }
                                    : {}),
                              },
                              key === "fresh"
                                ? "重新采集？"
                                : key === "pause"
                                  ? "暂停并停用计划？"
                                  : "归档任务？",
                              key === "fresh"
                                ? job.fresh_description
                                : "保留已归档业务数据；停止后续任务计划。",
                            ),
                        }}
                        trigger={["click"]}
                      >
                        <Button aria-label="任务更多操作">···</Button>
                      </Dropdown>
                    </>
                  )}
                </Space>
              </div>
              <Tabs
                className="detail-tabs"
                activeKey={tab}
                onChange={setTab}
                items={[
                  {
                    key: "runs",
                    label: "运行与记录",
                    children:
                      active && tab === "runs" ? (
                        <RunJournal key={job.id} job={job} />
                      ) : null,
                  },
                  {
                    key: "data",
                    label: "数据预览",
                    children:
                      active && tab === "data" ? (
                        <DataPreview key={job.id} project={job.id} />
                      ) : null,
                  },
                  {
                    key: "access",
                    label: "资源与身份",
                    children: (
                      <div className="task-access">
                        <div>
                          <strong>访问规则与采集出口</strong>
                          <p>管理平台共享频控，查看出口设备与分配状态。</p>
                          <Space>
                            <Button onClick={() => onPage("sites")}>
                              站点访问规则
                            </Button>
                            <Button onClick={() => onPage("exits")}>
                              查看采集出口
                            </Button>
                          </Space>
                        </div>
                        <div>
                          <strong>平台身份</strong>
                          <p>集中查看平台身份档案、当前操作和节点诊断。</p>
                          <Button onClick={() => onPage("identities")}>
                            管理平台身份
                          </Button>
                        </div>
                        <div>
                          <strong>共享下载资源</strong>
                          <p>
                            所有任务共享下载窗口与缓冲额度，保存后正常重启生效。
                          </p>
                          <Button onClick={() => onPage("resources")}>
                            配置共享资源
                          </Button>
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: "rules",
                    label: "采集说明",
                    children: (
                      <>
                        <QueryNotice query={rules} />
                        {rules.data ? (
                          <CollectionRules rule={rules.data} />
                        ) : (
                          <Empty description="暂无来源说明" />
                        )}
                      </>
                    ),
                  },
                ]}
              />
              {editing && (
                <Plan
                  key={job.id}
                  job={job}
                  drafts={drafts.current}
                  onClose={() => setEditing(false)}
                />
              )}
            </>
          ) : (
            <Empty
              description="请选择采集项；服务未就绪时请查看运行状态"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </section>
      </div>
    </div>
  );
}
