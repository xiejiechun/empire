import { useEffect, useState } from "react";
import {
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { Data, useQuery } from "./api";
import { QueryNotice } from "./shared";
const names: Record<string, string> = {
  announcement_date: "公告日期",
  period_basis: "期间口径",
  basis: "来源口径",
  source_time: "来源时刻",
  price: "价格",
  average_price: "均价",
  source_volume: "来源成交量",
  source_turnover: "来源成交额",
  source_flag: "来源标记",
  reason: "原因",
  actor: "变动主体",
  forecast_type: "预告类型",
  forecast_text: "预告内容",
  theme_id: "题材编号",
  brief: "简介",
  introduction: "介绍",
  member_count: "成员数",
  holding_count: "持股数",
  rank: "排名",
  shares: "股数",
  holder_name: "股东名称",
  security: "证券代码（含市场）",
  code: "证券 / 指数代码",
  industry: "行业代码",
  market: "市场",
  search: "关键词",
  start: "开始日期",
  end: "结束日期",
  day: "查询日期",
  month: "查询月份",
  unified_code: "证券代码",
  name: "名称",
  report_date: "报告期",
  trade_date: "交易日期",
  published_at: "发布时间",
  title: "标题",
  content: "正文",
  source: "来源",
  open: "开盘价",
  high: "最高价",
  low: "最低价",
  close: "收盘价",
  volume_shares: "成交量（股）",
  amount_yuan: "成交额（元）",
  is_trade: "是否交易日",
  updated_at: "更新时间",
  observed_at: "核验时间",
  stock_name: "证券名称",
  industry_name: "行业名称",
  index_name: "指数名称",
  index_code: "指数代码",
  pool_type: "池类型",
  status: "状态",
  availability: "数据可用性",
  record_key: "业务记录键",
  section: "栏目",
  items: "科目明细",
  rows: "数据明细",
  members: "成员明细",
  fields: "科目明细（元）",
  values: "数据值",
  amount: "金额",
  quantity: "数量",
  ratio: "比例",
  holder: "股东",
  currency: "币种",
  description: "说明",
  current_date: "当前日期",
};
function value(v: any): string {
  return v == null
    ? "—"
    : typeof v === "boolean"
      ? v
        ? "是"
        : "否"
      : typeof v === "object"
        ? "查看明细"
        : ({source_report:"来源报表",year_to_date:"年初至今",instant:"期末时点",CNY:"人民币",SH:"沪市",SZ:"深市",BJ:"北交所"} as Record<string,string>)[String(v)] || String(v);
}
function ReadValue({ data }: { data: any }) {
  if (data == null || typeof data !== "object")
    return <span style={{ whiteSpace: "pre-wrap" }}>{value(data)}</span>;
  if (Array.isArray(data))
    return (
      <div>
        {data.length
          ? data.map((r, i) => (
              <div className="preview-detail-item" key={i}>
                <ReadValue data={r} />
              </div>
            ))
          : "无明细"}
      </div>
    );
  return (
    <Descriptions
      size="small"
      column={1}
      bordered
      items={Object.entries(data).map(([k, v]) => ({
        key: k,
        label: names[k] || k,
        children: <ReadValue data={v} />,
      }))}
    />
  );
}
export default function DataPreview({ project }: { project: string }) {
  const catalog = useQuery("preview.catalog", { ident: project }, 60000);
  const [view, setView] = useState(""),
    [draft, setDraft] = useState<Data>({}),
    [filters, setFilters] = useState<Data>({}),
    [stack, setStack] = useState<any[]>([null]),
    [selected, setSelected] = useState<Data>();
  const spec = (catalog.data || []).find((v: Data) => v.id === view);
  useEffect(() => {
    if (catalog.data?.length && !view) {
      setView(catalog.data[0].id);
      setDraft(catalog.data[0].defaults || {});
      setFilters(catalog.data[0].defaults || {});
    }
  }, [catalog.data]);
  const query = useQuery(
    "preview.read",
    {
      ident: project,
      view,
      filters,
      cursor: JSON.stringify(stack[stack.length - 1]),
    },
    60000,
    !!spec,
  );
  const rows = query.data?.rows || [];
  const keys = [...new Set<string>(rows.flatMap((r: Data) => Object.keys(r)))];
  const ordered = [
    ...[
      "unified_code",
      "code",
      "name",
      "report_date",
      "trade_date",
      "published_at",
      "title",
    ].filter((k) => keys.includes(k)),
    ...keys.filter(
      (k) =>
        ![
          "unified_code",
          "code",
          "name",
          "report_date",
          "trade_date",
          "published_at",
          "title",
        ].includes(k),
    ),
  ];
  return (
    <div className="data-preview">
      <QueryNotice query={catalog} />
      <div className="preview-query">
        <Select
          aria-label="预览数据类型"
          style={{ minWidth: 200 }}
          value={view || undefined}
          options={(catalog.data || []).map((v: Data) => ({
            value: v.id,
            label: v.title,
          }))}
          onChange={(v) => {
            setView(v);
            const defaults = catalog.data.find((item: Data) => item.id === v)?.defaults || {};
            setDraft(defaults);
            setFilters(defaults);
            setStack([null]);
            setSelected(undefined);
          }}
        />
        {(spec?.filters || []).map((key: string) => (
          <label key={key}>
            <span>{names[key] || key}</span>
            <Input
              aria-label={names[key] || key}
              type={
                ["start", "end", "day"].includes(key)
                  ? "date"
                  : key === "month"
                    ? "month"
                    : "text"
              }
              value={draft[key] || ""}
              placeholder={key === "security" ? "000001.SZ" : names[key]}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              onPressEnter={() => {
                setFilters(draft);
                setStack([null]);
                query.refresh();
              }}
            />
          </label>
        ))}
        <Button
          type="primary"
          onClick={() => {
            setFilters(draft);
            setStack([null]);
            query.refresh();
          }}
        >
          查询 / 刷新
        </Button>
      </div>
      <QueryNotice query={query} />
      <div className="preview-caption">
        <span>
          {query.data?.message ||
            "查看当前采集项对应的数据，读取不会启动采集。"}
        </span>
        <Tag>{query.data?.storage || "只读预览"}</Tag>
      </div>
      <Table<Data>
        size="small"
        rowKey={(_, i) => String(i)}
        dataSource={rows}
        pagination={false}
        scroll={{ x: "max-content", y: "max(160px, calc(100vh - 570px))" }}
        columns={[
          ...ordered.slice(0, 10).map((k) => ({
            title: names[k] || k,
            dataIndex: k,
            width: k === "title" ? 320 : 150,
            ellipsis: true,
            render: (v: any, r: Data) =>
              typeof v === "object" && v != null ? (
                <Button type="link" onClick={() => setSelected(r)}>
                  查看明细
                </Button>
              ) : (
                value(v)
              ),
          })),
          {
            title: "",
            key: "detail",
            width: 80,
            fixed: "right" as const,
            render: (_: any, r: Data) => (
              <Button type="link" onClick={() => setSelected(r)}>
                详情
              </Button>
            ),
          },
        ]}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                query.data?.required
                  ? query.data.message
                  : query.error
                    ? "查询未成功，请检查条件后重试"
                    : "当前条件下没有记录；不代表该范围已采齐"
              }
            />
          ),
        }}
      />
      <div className="preview-footer">
        <span className="muted">
          {rows.length} 条 · 第 {stack.length} 页
          {query.data?.total != null ? ` · 共 ${query.data.total} 条` : ""}
        </span>
        <Space>
          <Button
            disabled={stack.length === 1}
            onClick={() => setStack(stack.slice(0, -1))}
          >
            上一页
          </Button>
          <Button
            disabled={query.data?.next == null || !!query.error}
            onClick={() => setStack([...stack, query.data.next])}
          >
            下一页
          </Button>
        </Space>
      </div>
      <Drawer
        title="数据详情"
        size={760}
        open={!!selected}
        onClose={() => setSelected(undefined)}
      >
        <ReadValue data={selected} />
      </Drawer>
    </div>
  );
}
