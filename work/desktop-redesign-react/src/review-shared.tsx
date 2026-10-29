import { useCallback, useLayoutEffect, useState } from 'react';
import { Badge, Button, Empty, Tooltip } from 'antd';
import { ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import type { RunState } from './review-data';

// Observe the current viewport, not the node that happened to exist on first mount.
// Hidden pages report zero dimensions: keep the last valid size until revealed.
export function useStageHeight() {
  const [stage, setStage] = useState<HTMLDivElement | null>(null);
  const [height, setHeight] = useState(400);
  const ref = useCallback((node: HTMLDivElement | null) => setStage(node), []);
  useLayoutEffect(() => {
    if (!stage) return;
    const header = stage.querySelector<HTMLElement>('.ant-table-header');
    const measure = () => {
      if (stage.clientHeight === 0 || stage.clientWidth === 0) return;
      const available = Math.max(1, Math.floor(stage.clientHeight - (header?.getBoundingClientRect().height ?? 0) - 1));
      setHeight(previous => previous === available ? previous : available);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    if (header) observer.observe(header);
    measure();
    return () => observer.disconnect();
  }, [stage]);
  return { ref, height };
}
// Chart coordinates follow the rendered SVG box so labels stay legible without letterboxing.
export function useChartBox() {
  const [node, setNode] = useState<SVGSVGElement | null>(null);
  const [size, setSize] = useState({width:920, height:300});
  const ref = useCallback((element:SVGSVGElement|null) => setNode(element), []);
  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => {
      const {width,height} = node.getBoundingClientRect();
      if (width <= 0 || height <= 0) return;
      setSize(old => old.width===width && old.height===height ? old : {width,height});
    };
    const observer = new ResizeObserver(measure);
    observer.observe(node); measure();
    return () => observer.disconnect();
  }, [node]);
  return {ref,...size};
}
export function RunBadge({ state }: { state: RunState }) {
  const status = ({ '采集中':'processing', '等待归档':'warning', '请求失败':'error', '来源缺口':'warning', '已核验':'success', '已暂停':'default' } as const)[state];
  return <Badge status={status} text={state} />;
}
export function Tools({ refresh, columns }: { refresh: () => void; columns?: () => void }) {
  return <div className="small-actions"><Tooltip title="刷新示例"><Button type="text" aria-label="刷新示例" icon={<ReloadOutlined />} onClick={refresh} /></Tooltip>{columns && <Tooltip title="显示列"><Button type="text" aria-label="显示列" icon={<SettingOutlined />} onClick={columns} /></Tooltip>}</div>;
}
export function NoResults({ reset }: { reset: () => void }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的结果"><Button onClick={reset}>清除筛选</Button></Empty>;
}
