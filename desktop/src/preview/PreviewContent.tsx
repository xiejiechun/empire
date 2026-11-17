import { Alert, Empty } from "antd";
import { PreviewProps } from "./presentation";
import { StatementView } from "./StatementView";
import { CalendarView, PriceView } from "./MarketViews";
import { EventView, HoldingsView, HotListView, NewsView } from "./ReportViews";
import { DirectoryView, PoolView, ReasonView, RulesView, ThemesView } from "./CatalogueViews";
import "./renderers.css";
import { FundFlowView } from "./FundFlowView";

export default function PreviewContent(props: PreviewProps) {
  const renderers: Record<string, React.ComponentType<PreviewProps>> = {
    statement: StatementView, prices: PriceView, calendar: CalendarView, news: NewsView,
    holdings: HoldingsView, hotlist: HotListView, events: EventView, capital: EventView,
    directory: DirectoryView, themes: ThemesView, pool: PoolView, rules: RulesView, reason: ReasonView, fundflow: FundFlowView,
  };
  const Content = renderers[props.spec.renderer];
  const hasEmptyContext = props.spec.renderer === "calendar" || props.spec.renderer === "themes" && props.context?.head
    || props.spec.renderer === "fundflow" && props.context?.snapshot?.available;
  return <div className="pv-content" data-preview-kind={props.spec.renderer}>{!Content
    ? <Alert type="warning" showIcon title="此项目尚未登记专用预览布局" description="请更新客户端的项目预览登记。" />
    : !props.rows.length && !hasEmptyContext ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`${props.spec.title}：当前条件下没有已取得的记录；不代表该范围已采集完整。`} />
    : <Content {...props} />}</div>;
}
export { PreviewContent };
