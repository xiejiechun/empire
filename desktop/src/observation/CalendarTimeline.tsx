import { useLayoutEffect, useRef, type ComponentProps, type RefObject } from 'react';
import { Button } from 'antd';
import MonthGrid from './MonthGrid';
import type { MonthResult } from './model';

type GridProps = Omit<ComponentProps<typeof MonthGrid>, 'rows' | 'month'>;
export default function CalendarTimeline({ months, loading, error, hasPrevious, onLoadPrevious, scrollRef, ...grid }: GridProps & {
  months: MonthResult[]; loading?: boolean; error?: string; hasPrevious: boolean; onLoadPrevious: () => void;
  scrollRef: RefObject<HTMLDivElement | null>;
}) {
  const anchor = useRef<{ height: number; top: number } | null>(null);
  const lastTop = useRef(0);
  const load = () => {
    const el = scrollRef.current;
    if (!el || loading || !hasPrevious) return;
    anchor.current = { height: el.scrollHeight, top: el.scrollTop };
    onLoadPrevious();
  };
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && anchor.current) {
      el.scrollTop = anchor.current.top + el.scrollHeight - anchor.current.height;
      lastTop.current = el.scrollTop;
      anchor.current = null;
    }
  }, [months.length, scrollRef]);
  return <div className="observation-scroll" ref={scrollRef} aria-label="连续月份观察窗口"
    onWheel={e => { if (e.deltaY < 0 && e.currentTarget.scrollTop <= 2 && !error) load(); }}
    onScroll={e => {
      const top = e.currentTarget.scrollTop;
      if (top <= 2 && lastTop.current > top && !error) load();
      lastTop.current = top;
    }}>
    <div className="observation-history-controls">
      <Button aria-label={error ? '重试加载更早月份' : hasPrevious ? '向上加载更早月份' : '已到最早观察月份'} type="text" size="small" loading={loading} disabled={!hasPrevious} onClick={load}>
        {error ? '重试加载更早月份' : hasPrevious ? '向上加载更早月份' : '已到最早观察月份'}
      </Button>
      {error ? <span role="alert">历史月份读取失败：{error}</span> : <span>{months.length > 1 ? `已展开 ${months.length} 个月 · ` : ''}每次追加完整月份</span>}
    </div>
    {months.map(result => <section className="observation-month" data-month={result.month} key={result.month}>
      <div className="observation-month-title"><b>{result.month.replace('-', '年 ')}月</b><span>{result.month === months.at(-1)?.month ? '观察月份' : '历史月份'}</span></div>
      <MonthGrid {...grid} rows={result.rows} month={result.month} />
    </section>)}
  </div>;
}
