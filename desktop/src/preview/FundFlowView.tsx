import { Empty, Tag } from "antd";
import { PreviewProps, RecordTable } from "./presentation";

export function FundFlowView({ spec, rows, context }: PreviewProps) {
  const snapshot = context?.snapshot;
  const clock = (value: string) => new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(value));
  return <div className="pv-fundflow">
    {snapshot?.available && <div className="pv-fundflow-summary" aria-label="资金榜采样信息">
      <div><span>交易日期</span><strong>{snapshot.date}</strong></div>
      <div><span>采样区间 · 北京时间</span><strong>{clock(snapshot.started)} — {clock(snapshot.finished)}</strong></div>
      <div><span>完整快照</span><strong>{context?.source_total?.toLocaleString("zh-CN")} 只证券</strong></div>
      <Tag color="orange">盘中采样 · 未归档</Tag>
    </div>}
    {!snapshot && <p className="pv-subtle">历史日榜 · 当天盘中记录请切换“盘中资金榜”。</p>}
    {rows.length ? <RecordTable spec={spec} rows={rows} /> : <Empty description="快照已取得，当前证券筛选没有匹配记录。" />}
    <p className="pv-note">金额按元、万、亿显示，悬停可看精确原值；活跃度和涨跌幅显示百分比。来源序号不代表资金排名。</p>
  </div>;
}
