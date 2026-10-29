import { Alert, Descriptions, Empty, Table, Tag } from "antd";
import { label, time } from "./api";
export function QueryNotice({
  query,
}: {
  query: { data: any; error: string; stamp?: number };
}) {
  return query.error ? (
    <Alert
      showIcon
      type="warning"
      title="读取失败"
      description={`${query.error}${query.data ? " · 显示上次成功快照，已过期：" + time((query.stamp || 0) / 1000) : ""}`}
    />
  ) : null;
}
export function Status({ value }: { value: string }) {
  return (
    <Tag
      color={
        ["failed", "error"].includes(value)
          ? "red"
          : value === "running"
            ? "blue"
            : value === "source_gap" || value === "awaiting_archive"
              ? "orange"
              : "default"
      }
    >
      {label(value)}
    </Tag>
  );
}
export function Details({ value }: { value: any }) {
  if (value == null)
    return (
      <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    );
  if (typeof value !== "object") return <span>{String(value)}</span>;
  return (
    <Descriptions
      size="small"
      bordered
      column={1}
      items={Object.entries(value).map(([key, v]) => ({
        key,
        label: key,
        children:
          typeof v === "object" && v !== null ? (
            <pre className="json-detail">{JSON.stringify(v, null, 2)}</pre>
          ) : (
            String(v ?? "未知")
          ),
      }))}
    />
  );
}
export function ObjectTable({ rows }: { rows: any[] }) {
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 8);
  return (
    <Table
      size="small"
      rowKey={(r) => r.id || r.code || r.name || JSON.stringify(r)}
      scroll={{ x: true }}
      pagination={false}
      dataSource={rows}
      columns={keys.map((key) => ({
        title: key,
        dataIndex: key,
        render: (v) =>
          typeof v === "object" ? JSON.stringify(v) : String(v ?? "未知"),
      }))}
    />
  );
}
