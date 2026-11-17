import { useEffect, useRef, useState } from 'react';
import { chinaToday, type Day, type MonthResult } from './model';

type Live = Pick<Day, 'date' | 'values' | 'sources'> & { warnings: string[]; queried_at: string };
type State = { identity: string; data?: Live; error?: string; loading?: boolean };

// A separate overlay: polling never changes the month query or timeline identity.
export function useLiveRefresh(identity: string, months: MonthResult[]) {
  const [enabled, setEnabled] = useState(true), [seconds, setSeconds] = useState(30);
  const [state, setState] = useState<State>({ identity: '' });
  const refresh = useRef<() => void>(() => {});
  const today = chinaToday();
  const basis = months.flatMap(m => m.rows).find(r => r.date === today && Object.keys(r.live_basis || {}).length)?.live_basis || {};
  const key = JSON.stringify({ date: today, basis });
  const eligible = Object.keys(basis).length > 0;
  const scopeIdentity = identity + key;
  useEffect(() => {
    setState(s => ({ ...s, loading: false }));
    if (!eligible) { refresh.current = () => {}; return; }
    let disposed = false, busy = false, timer: ReturnType<typeof setTimeout> | undefined;
    let scope: string | undefined;
    const schedule = () => { if (enabled && !disposed) timer = setTimeout(tick, seconds * 1000); };
    const tick = async () => {
      if (disposed || busy) return;
      clearTimeout(timer);
      if (JSON.parse(key).date !== chinaToday()) {
        setState(s => ({ ...s, identity: scopeIdentity, loading: false, error: '日期已变化，请点击“刷新数据”加载今天' }));
        return;
      }
      busy = true; scope = crypto.randomUUID();
      setState(s => ({ ...(s.identity === scopeIdentity ? s : {}), identity: scopeIdentity, loading: true }));
      try {
        const data: Live = await window.empire.read('observation.live', JSON.parse(key), scope);
        if (!disposed && data.date === chinaToday()) setState(s => ({ identity: scopeIdentity,
          data: { ...data, values: { ...(s.identity === scopeIdentity ? s.data?.values : {}), ...data.values },
            sources: { ...(s.identity === scopeIdentity ? s.data?.sources : {}), ...data.sources } },
          error: data.warnings.length ? '部分盘中数据未更新，保留上次报价' : undefined }));
      } catch {
        if (!disposed) setState(s => ({ ...(s.identity === scopeIdentity ? s : {}), identity: scopeIdentity, error: '刷新失败，保留上次报价' }));
      } finally {
        busy = false;
        if (!disposed) { setState(s => ({ ...s, loading: false })); schedule(); }
      }
    };
    refresh.current = () => { void tick(); };
    schedule();
    return () => { disposed = true; clearTimeout(timer); refresh.current = () => {};
      if (scope) void window.empire.cancel(scope).catch(() => {}); };
  }, [scopeIdentity, key, eligible, enabled, seconds]);
  const current = state.identity === scopeIdentity ? state : undefined;
  const merged = months.map(m => ({ ...m, rows: m.rows.map(row => {
    if (row.date !== today || !row.live_basis) return row;
    const keys = Object.keys(row.live_basis);
    const values = { ...row.values }, sources = { ...row.sources };
    for (const key of keys) {
      if (current?.data?.sources?.[key]) { values[key] = current.data.values[key]; sources[key] = current.data.sources[key]; }
      if (sources[key]) sources[key] = { ...sources[key], sampling_stale: sources[key].sampling_stale || Date.now() - Date.parse(sources[key].observed_at) > 180000 };
    }
    return { ...row, values, sources };
  }) }));
  const sources = merged.flatMap(m => m.rows).find(r => r.date === today)?.sources || {};
  return { months: merged, enabled, setEnabled, seconds, setSeconds, eligible, loading: !!current?.loading,
    error: current?.error, sources, updatedAt: current?.data?.queried_at, refresh: () => refresh.current() };
}
