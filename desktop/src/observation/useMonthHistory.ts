import { useEffect, useRef, useState } from 'react';
import { shiftMonth, type MonthResult } from './model';

// One complete month per read; a scope change cancels and hides all older reads.
export function useMonthHistory(identity: string, current: MonthResult | undefined, params: object) {
  const [state, setState] = useState<{ identity: string; months: MonthResult[]; loading?: boolean; error?: string }>({ identity: '', months: [] });
  const request = useRef<{ scope: string; identity: string } | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setState({ identity, months: [] });
    return () => {
      generation.current++;
      const pending = request.current;
      request.current = null;
      if (pending) void window.empire.cancel(pending.scope).catch(() => {});
    };
  }, [identity]);
  const active = state.identity === identity ? state : { identity, months: [] };
  const earliest = active.months[0]?.month || current?.month;
  const loadPrevious = () => {
    if (!current || !earliest || earliest <= '1991-01' || request.current) return;
    const month = shiftMonth(earliest, -1), scope = crypto.randomUUID(), version = generation.current;
    request.current = { scope, identity };
    setState({ ...active, loading: true, error: undefined });
    window.empire.read('observation.read', { ...params, month }, scope).then(
      (data: MonthResult) => {
        if (generation.current !== version) return;
        if (data.month !== month) throw new Error('历史月份与请求不一致');
        setState({ identity, months: [data, ...active.months] });
      },
    ).catch(error => {
      if (generation.current === version) setState({ ...active, loading: false, error: String(error) });
    }).finally(() => { if (request.current?.scope === scope) request.current = null; });
  };
  return { ...active, hasPrevious: !!earliest && earliest > '1991-01', loadPrevious };
}
