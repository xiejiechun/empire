import { Checkbox, Tag } from 'antd';
import type { ReactNode } from 'react';
import { orderAmount, percent, signed, type ReviewReport, type ReviewStock } from './report';

export function Detail({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return <details className="review-detail" open={open || undefined}><summary>{title}</summary><div>{children}</div></details>;
}

function Change({ value, suffix = '%' }: { value: number; suffix?: string }) {
  return <span className={value > 0 ? 'review-up' : value < 0 ? 'review-down' : ''}>{signed(value)}{suffix}</span>;
}

export function Ladder({ report, onStock }: { report: ReviewReport; onStock: (stock: ReviewStock) => void }) {
  return <>
    <div className="review-table-scroll"><table aria-label="虚拟连板梯队"><thead><tr><th>高度</th><th>证券 / 题材</th><th>首封</th><th className="review-num">收盘封单</th></tr></thead><tbody>{report.stocks.map(s => <tr key={s.name}><td><span className="review-board">{s.height}板</span></td><td><button className="review-stock" onClick={() => onStock(s)}>{s.name}</button><small>{s.topic} · {s.boardType}</small></td><td>{s.firstSealed}</td><td className="review-num">{orderAmount(s.orderWan)}</td></tr>)}</tbody></table></div>
    <Detail title={`首板${report.market.firstBoards}家 · 按题材分组`} open>
      <div className="review-first-themes">{report.firstThemes.map(t => <div key={t.name}><strong>{t.name}</strong><span>{t.representatives}</span><small>{t.count}家</small></div>)}</div>
      <p className="review-muted">虚拟分类互不重叠，数量合计{report.firstThemes.reduce((a, v) => a + v.count, 0)}家；名称为代表证券。</p>
    </Detail>
  </>;
}

export function Promotion({ report }: { report: ReviewReport }) {
  const p = report.promotion;
  return <>
    <div className="review-grid-two review-promotion">
      <div><small>昨日2板 → 今日3板</small><h2>{p.secondPromoted.length} / {p.secondYesterday} <small>{percent(p.secondPromoted.length, p.secondYesterday)}</small></h2><p>晋级：{p.secondPromoted.join('、')}</p></div>
      <div><small>昨日首板 → 今日2板</small><h2>{p.firstPromoted.length} / {p.firstYesterday} <small>{percent(p.firstPromoted.length, p.firstYesterday)}</small></h2><p>{p.firstPromoted.join('、')}</p></div>
    </div>
    <Detail title="未晋级与断板表现">
      <p className="review-muted">昨日2板共{p.secondYesterday - p.secondPromoted.length}家未晋级，下列为代表证券。</p>
      <div className="review-table-scroll"><table aria-label="虚拟断板代表证券"><thead><tr><th>证券</th><th>方向</th><th className="review-num">本日收盘</th></tr></thead><tbody>{p.failed.map(s => <tr key={s.name}><td>{s.name}</td><td>{s.topic}</td><td className="review-num"><Change value={s.change} /></td></tr>)}</tbody></table></div>
      <p className="review-muted">昨日{p.formerHigh.previousHeight}板观察：{p.formerHigh.name}收盘<Change value={p.formerHigh.change} />，未晋级。</p>
    </Detail>
    <div className="review-risk">市场普涨与中位晋级不同步，下一交易日优先验证接力。</div>
  </>;
}

export function Judgments({ report }: { report: ReviewReport }) {
  return <div className="review-judgments">{report.judgments.map(j => <div key={j.label}><span>{j.label}</span><div><strong>{j.title}</strong><p>{j.evidence}</p></div></div>)}</div>;
}

export function Plans({ report, selected, onChange }: { report: ReviewReport; selected: string[]; onChange: (id: string, value: boolean) => void }) {
  return <><div className="review-plan-hint"><Tag>虚拟预案</Tag><span>勾选后保存在本机，用于后续逐项完善。</span></div>{report.plans.map((p, i) => <article className="review-plan" key={p.id}>
    <span className="review-plan-number">{String(i + 1).padStart(2, '0')}</span><div><div className="review-plan-heading"><h3>{p.title}</h3><Checkbox checked={selected.includes(p.id)} onChange={e => onChange(p.id, e.target.checked)} aria-label={`将${p.title}列入预案`}>列入预案</Checkbox></div><p>{p.target}</p><div className="review-conditions"><span>确认</span><p>{p.confirm}</p><span>转弱</span><p>{p.weaken}</p></div></div>
  </article>)}</>;
}
