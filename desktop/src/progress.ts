import { Data } from './api';
export function progressPercent(progress: Data = {}): number | undefined {
  const done = progress.completed_units ?? progress.processed_units;
  const total = progress.total_units;
  if (typeof done !== 'number' || !Number.isFinite(done) || done < 0 ||
      typeof total !== 'number' || !Number.isFinite(total) || total <= 0) return undefined;
  return Math.max(0, Math.min(100, Math.floor(done * 100 / total)));
}
