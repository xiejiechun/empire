import { Collapse, Descriptions, Empty, Typography } from "antd";
import { Data } from "./api";

function Addresses({ values }: { values: string[] }) {
  return <div className="rule-addresses">{values.map(value =>
    <Typography.Text key={value} code copyable={{ text: value }}>{value}</Typography.Text>
  )}</div>;
}

export default function CollectionRules({ rule }: { rule: Data }) {
  const s = rule.storage;
  if (!s) return <Empty description="暂无存储说明，请检查后台版本" />;
  const item = (key: string, label: string, children: React.ReactNode) => ({ key, label, children });
  if (s.latest) return <section className="collection-rules" aria-label="采集说明">
    <Descriptions column={1} size="small" bordered items={[
      item("scope", "采集内容", rule.scope),
      item("update", "更新方式", rule.incremental),
      item("latest", "Redis 最新行情", <><Addresses values={[s.latest]} /><small>每个品种仅一份最新值，无分钟历史或快照。采样超过180秒标记过期。</small></>),
      item("mysql", "日线归档", "实时任务不发布归档消息、不访问日线业务表；历史日K线在独立的汇率历史日线任务查看。"),
      item("recovery", "恢复与保留", <>{rule.recovery}<br />整键最后成功写入7天过期，Redis或电脑重启丢失后重新采样；失败保留旧值。</>),
      item("limits", "来源时间", rule.limits),
    ]} />
    <Collapse ghost items={[{ key: "source", label: "来源接口与参数", children: rule.requests.map((r: Data, index: number) =>
      <div key={index}><strong>{r.purpose} · {r.method}</strong><Addresses values={[r.url]} />
        <Descriptions column={1} size="small" items={r.parameters.map((p: Data) => item(p.name, p.name, <>{p.value} — {p.meaning}</>))} /></div>) }]} />
  </section>;
  return <section className="collection-rules" aria-label="采集说明">
    <p className="muted">路径来自当前程序配置；这里说明数据去向，不表示已经采集完成。</p>
    <Descriptions column={1} size="small" bordered items={[
      item("scope", "采集内容", rule.scope),
      item("range", "时间范围", <>{rule.start}<br />至：{rule.end}</>),
      item("update", "更新方式", rule.incremental),
      ...(s.intraday ? [item("intraday", "盘中数据", <>
        <Addresses values={[s.intraday.body]} /><small>{s.intraday.note}</small>
      </>)] : []),
      item("redis", s.intraday ? "日终 Redis 队列" : "Redis 待归档", <>
        <Addresses values={[s.queue]} /><small>共享 Stream；按本任务 job_key / dataset 区分消息，成功归档即删除，失败保留。</small>
      </>),
      item("mysql", s.intraday ? "日终 MySQL 表" : "MySQL 业务表", <>
        <small>数据库：<Typography.Text code>{s.database}</Typography.Text></small>
        <Addresses values={s.tables} />
      </>),
      item("safety", "去重与恢复", "可信摘要命中不访问 MySQL；缓存失效回库核对。旧版本不覆盖新数据，失败不跳过断点。"),
    ]} />
    <Collapse ghost items={[
      { key: "keys", label: "更多存储位置 · 断点、摘要、记录与配置", children:
        <Descriptions column={1} size="small" items={[
          item("identity", "消息筛选", <><small>Stream 的 envelope 字段内，按 job_key 和以下 dataset 筛选。</small><Typography.Text code>job_key={rule.job_key}</Typography.Text><Addresses values={rule.datasets} /></>),
          item("checkpoint", "Redis 断点 · Hash", <Addresses values={[s.checkpoint]} />),
          item("progress", "Redis 归档进度", <Addresses values={[s.progress]} />),
          item("fingerprints", "Redis 摘要", <><Addresses values={s.fingerprints} /><small>Hash 保存摘要与版本；每个键配套 :expiry ZSET。有效期与容量按归档配置。</small></>),
          ...(s.intraday ? [item("indexes", "盘中索引与状态", <Addresses values={s.intraday.keys} />)] : []),
          item("records", "Redis 运行与错误", <><Addresses values={[s.control, s.archives, s.errors]} /><small>依次为共享采集运行状态、项目归档记录、项目错误；运行/归档各保留最近 100 条，错误最多 300 条。</small></>),
          item("state", "MySQL 归档状态", <><Typography.Text code>{s.state_table}</Typography.Text><small>namespace={s.namespace}；project_id={s.state_project}。每项目一行，摘要命中不刷新 SQL 状态。</small></>),
          item("settings", "MySQL 任务配置", <><Typography.Text code>{s.settings_table}</Typography.Text><small>namespace={s.namespace}；kind=task；setting_key={s.state_project}。</small></>),
          item("volatile", "保留边界", "Redis 为临时内存数据，服务或电脑重启会丢失；MySQL 保存正式业务。成功响应原文不长期保存。"),
        ]} /> },
      { key: "lifecycle", label: "采集与恢复细则", children:
        <Descriptions column={1} size="small" items={[
          item("initial", "首次采集", rule.initial), item("fresh", "重新采集", rule.fresh),
          item("recovery", "中断与重启", rule.recovery), item("limits", "用途限制", rule.limits),
        ]} /> },
      { key: "requests", label: "来源接口与参数", children: rule.requests.map((r: Data, index: number) =>
        <div className="rule-request" key={index}>
          <strong>{r.purpose} · {r.method}</strong><Addresses values={[r.url]} />
          <Descriptions column={1} size="small" items={r.parameters.map((p: Data) =>
            item(p.name, p.name, <>{p.value} <span className="muted">— {p.meaning}</span></>))} />
          {!r.parameters.length && <small>无请求参数</small>}
        </div>) },
    ]} />
  </section>;
}
