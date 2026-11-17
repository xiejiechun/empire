import type { ReviewReport } from './report';

const KEY = 'empire.daily-review.demo.v1';
export type SavedReview = { note: string; plans: string[] };
type StoredReview = { version: 1; reportId: string; note: string; plans: string[] };
const drafts = new Map<string, string>();
export const reading = { selectedDate: '', scrollTop: 0, collapsed: [] as string[] };

export function reviewToday(): string {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
}

export function loadReview(report: ReviewReport): { value: SavedReview; warning: string } {
  const initial = { note: '', plans: report.plans.slice(0, 2).map(p => p.id) };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { value: initial, warning: '' };
    const stored: unknown = JSON.parse(raw);
    if (!stored || typeof stored !== 'object') throw new Error();
    const v = stored as Partial<StoredReview>;
    if (v.version !== 1 || v.reportId !== report.id || typeof v.note !== 'string' ||
      v.note.length > 4000 || !Array.isArray(v.plans) || v.plans.length > report.plans.length ||
      !v.plans.every((id): id is string => typeof id === 'string' && report.plans.some(p => p.id === id))) throw new Error();
    return { value: { note: v.note, plans: [...new Set(v.plans)] }, warning: '' };
  } catch {
    return { value: initial, warning: '本机复盘记录无法读取，已使用默认预案；保存前请核对内容。' };
  }
}

export function saveReview(report: ReviewReport, value: SavedReview): string {
  try {
    localStorage.setItem(KEY, JSON.stringify({ version: 1, reportId: report.id, ...value }));
    return '';
  } catch {
    return '本机保存失败，当前内容仍保留在页面中；请稍后重试。';
  }
}

export const loadDraft = (id: string, saved: string) => drafts.get(id) ?? saved;
export function rememberDraft(id: string, value: string) { drafts.set(id, value); }
