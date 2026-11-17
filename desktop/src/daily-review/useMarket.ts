import { useEffect, useState } from 'react';

type Value = number | string | null;
export type CapitalStock = { unified_code: string; name: string; amount_yuan: Value; change_ratio: Value };
export type SectorRow = { industry_code: string; name: string; amount_yuan: Value; member_count: number; covered_count: number };
export type SectorData = { inflow: SectorRow[] | null; outflow: SectorRow[] | null; basis_observed_at: string | null; industry_count: number; complete_count: number; partial_count: number; uncovered_count: number; issue: string };
export type EtfEstimate = { amount_yuan: Value; covered_count: number; candidate_count: number; target_count: number; missing: { missing_shares: number; missing_nav: number; income_only: number; unknown_currency: number; event_review: number } };
export type EtfFlow = { current: EtfEstimate | null; previous: EtfEstimate | null; basis: string; catalog_hash: string | null; issue: string };
export type MarketData = {
  date: string; status: 'closed' | 'rest' | 'pending' | 'future' | 'unknown';
  previous_date: string | null; next_date: string | null; queried_at: string;
  limit_up: number | null; limit_down: number | null; first_boards: number | null; chain: number | null;
  amount_yuan: Value; amount_change_yuan: Value; price_count: number; previous_price_count: number;
  main_flow_yuan: Value; advance: number | null; decline: number | null; flat: number | null; fund_count: number;
  capital: { visible_flow_yuan: Value; dark_flow_yuan: Value; inflow: CapitalStock[] | null; outflow: CapitalStock[] | null; sectors: SectorData; etf?: EtfFlow | null };
  indices: { name: string; code: string | null; close: Value; change: Value }[];
  overseas: { name: string; close: Value; change: Value }[]; issues: string[];
};

export function useMarket(date: string) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ date: string; data?: MarketData; error: string; loading: boolean }>({ date, error: '', loading: true });
  useEffect(() => {
    const scope = crypto.randomUUID();
    let disposed = false;
    setState(old => ({ date, data: old.date === date ? old.data : undefined, error: '', loading: true }));
    void window.empire.read('review.market', { date }, scope).then((data: MarketData) => {
      if (data.date !== date) throw Error('返回日期与所选日期不一致');
      if (!disposed) setState({ date, data, error: '', loading: false });
    }).catch(error => {
      if (!disposed) setState(old => ({ ...old, error: String(error), loading: false }));
    });
    return () => { disposed = true; void window.empire.cancel(scope).catch(() => {}); };
  }, [date, revision]);
  return { ...(state.date === date ? state : { date, error: '', loading: true, data: undefined }), refresh: () => setRevision(n => n + 1) };
}
