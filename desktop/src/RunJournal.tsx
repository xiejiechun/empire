import { useState } from "react";
import { Button, Collapse, Descriptions, Progress, Select, Tag } from "antd";
import { Data, label, time, useQuery } from "./api";
import { Details, QueryNotice, Status } from "./shared";
import { progressPercent } from "./progress";
import Events from "./Events";
export default function RunJournal({ job }: { job: Data }) {
  const history = useQuery("records.list", { kind: "collection", project: job.id, offset: 0, limit: 100 }, 5000);
  const [round, setRound] = useState("current");
  const [snapshot, setSnapshot] = useState<Data>();
  const latest = job.active || job.latest_run;
  const current = round === "current";
  const record = current ? latest : snapshot;
  const progress = current ? (job.active ? job.progress : job.latest_run?.result) || {} : record?.result || {};
  const status = current ? (job.active ? progress.status || "running" : job.last_status) : record?.status;
  const percent = progressPercent(progress);
  const done = progress.completed_units ?? progress.processed_units;
  const previous = (history.data?.rows || []).filter((r: Data) => r.run_id && r.run_id !== latest?.run_id);
  if (!current && snapshot && !previous.some((r: Data) => r.run_id === snapshot.run_id)) previous.unshift(snapshot);
  const unit = progress.unit_name || job.unit_name || "完整单元";
  const running = current && !!job.active;
  return (
    <div className="run-journal journal-redesign">
      <QueryNotice query={history} />
      <div className="run-context">
        <div><strong>{current ? (job.active ? "当前运行" : "最近运行") : "历史运行"}</strong><span className="muted">每轮采集与归档事件在这里一起查看</span></div>
        <Select aria-label="选择运行轮次" value={round} style={{ width: 285 }} onChange={(id) => {
          setRound(id); setSnapshot(previous.find((r: Data) => r.run_id === id));
        }} options={[
          { value: "current", label: job.active ? "当前运行 · 实时更新" : "最近一轮" },
          ...previous.map((r: Data) => ({value: r.run_id, label: `${time(r.started_at)} · ${label(r.status)}`})),
        ]} />
      </div>
      {!current && <div className="history-context"><span>正在查看历史轮次，当前任务仍按原计划运行。</span><Button size="small" onClick={() => setRound("current")}>返回当前</Button></div>}
      <section className="run-overview">
        <div className="run-overview-top">
          <div><Status value={status} /><h3>{progress.message || (current && (job.error || job.notice)) || (record ? (running ? "正在采集数据" : "本轮运行已结束") : "尚未运行")}</h3></div>
          <div className="run-percent"><strong>{percent == null ? "—" : `${percent}%`}</strong><span>{unit.includes("当前批") ? "当前批进度" : unit.includes("核验") ? "核验阶段进度" : "采集进度"}</span></div>
        </div>
        <Progress percent={percent ?? 0} showInfo={false} status={status === "error" || status === "failed" ? "exception" : running ? "active" : "normal"} />
        <div className="run-progress-caption"><span>{percent == null ? (progress.total_units === 0 ? "本轮没有待处理单元" : "总量尚未确认，暂不计算百分比") : `${done} / ${progress.total_units} ${unit}`}</span><span>{status === "awaiting_archive" ? "采集已入队 · 等待本轮归档确认" : running ? "进度随任务自动更新" : "按本轮实际结果展示"}</span></div>
        <div className="run-facts">
          <div><span>开始时间</span><strong>{record?.started_at ? time(record.started_at) : "—"}</strong></div>
          <div><span>{running ? "当前处理" : "结束时间"}</span><strong>{running ? progress.current_unit || progress.current_security || progress.current_month || progress.current_date || "等待任务更新" : record?.finished_at ? time(record.finished_at) : "—"}</strong></div>
          <div title="本轮累计入队，不是当前待归档数量"><span>本轮入队记录</span><strong>{progress.queued_records ?? "—"}</strong></div>
        </div>
        {progress.storage === "redis_only" && <Tag>盘中快照 · 仅保存 Redis</Tag>}
      </section>
      <div className="run-event-heading"><strong>运行记录</strong><span className="muted">采集与异常按所选轮次查看，归档查看本任务记录</span></div>
      <Events key={`${job.id}:${record?.run_id || "none"}`} project={job.id} runId={record?.run_id} />
      <Collapse ghost items={[{key: "diagnostics", label: "更多运行信息", children: <>
        {job.archive_metrics && <>
          <p className="muted">归档内容核验统计 · 自 {time(job.archive_metrics.since)} 归档服务启动起累计，包含重试，不随历史轮次切换。</p>
          <Descriptions size="small" column={2} items={[
            {key:"checked",label:"核验业务键",children:job.archive_metrics.checked},
            {key:"equal",label:"摘要相同免 SQL",children:job.archive_metrics.equal},
            {key:"stale",label:"旧版本免 SQL",children:job.archive_metrics.stale},
            {key:"missing",label:"缺少可信摘要",children:job.archive_metrics.missing},
            {key:"changed",label:"内容变化需核对",children:job.archive_metrics.changed},
            {key:"sql",label:"SQL 归档成功 / 尝试",children:`${job.archive_metrics.sql_successes} / ${job.archive_metrics.sql_attempts}`},
            {key:"written",label:"业务写入行数",children:job.archive_metrics.written},
          ]} />
          <p className="muted">仅统计进入内容核验的归档批次，不含采集规划查询、状态 SQL 或整批快速确认；写入行数不是磁盘写入次数。</p>
        </>}
        <Descriptions size="small" column={1} items={[{key:"id",label:"轮次编号",children:record?.run_id || "—"},{key:"next",label:"下次执行",children:current && job.next_due ? time(job.next_due) : "—"}]} />
        <Details value={record || progress} />
      </>}]} />
    </div>
  );
}
