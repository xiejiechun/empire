import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Alert, Button, Descriptions, Input, Modal, Tag, theme } from 'antd';
import { DownOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { Judgments, Ladder, Plans, Promotion } from './ReviewSections';
import Capital from './Capital';
import Market from './Market';
import { useMarket } from './useMarket';
import { demoReport, orderAmount, type ReviewStock } from './report';
import { loadDraft, loadReview, reading, rememberDraft, reviewToday, saveReview } from './localState';
import './dailyReview.css';

export default function DailyReview() {
  const report = demoReport;
  const [selectedDate, setSelectedDate] = useState(() => reading.selectedDate || reviewToday());
  const hasReport = selectedDate === report.reviewDate;
  const market = useMarket(selectedDate);
  const [{ value: initial, warning }] = useState(() => loadReview(report));
  const [saved, setSaved] = useState(initial), [plans, setPlans] = useState(initial.plans);
  const [draft, setDraft] = useState(() => loadDraft(report.id, initial.note));
  const [collapsed, setCollapsed] = useState(() => reading.collapsed);
  const [stock, setStock] = useState<ReviewStock>(), [noteOpen, setNoteOpen] = useState(false);
  const [notice, setNotice] = useState(warning), [noticeType, setNoticeType] = useState<'warning' | 'success'>('warning');
  const scroll = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();
  const colors = {
    '--review-up': token.colorErrorText, '--review-down': token.colorSuccessText,
    '--review-orange': token.colorWarningText, '--review-purple': token.purple,
    '--review-pink': token.magenta,
  } as CSSProperties;

  useEffect(() => {
    const el = scroll.current;
    if (el) el.scrollTop = reading.scrollTop;
    return () => { if (el) reading.scrollTop = el.scrollTop; };
  }, []);
  function selectDate(value: string) {
    reading.selectedDate = value;
    setSelectedDate(value);
    setStock(undefined);
    setNoteOpen(false);
    if (scroll.current) scroll.current.scrollTop = 0;
    reading.scrollTop = 0;
  }
  function toggleBranch(id: string) {
    const next = collapsed.includes(id) ? collapsed.filter(k => k !== id) : [...collapsed, id];
    reading.collapsed = next;
    setCollapsed(next);
  }
  function persist(note: string, nextPlans: string[], reason: string) {
    const next = { note, plans: nextPlans }, failure = saveReview(report, next);
    setNotice(failure || reason);
    setNoticeType(failure ? 'warning' : 'success');
    if (!failure) setSaved(next);
    return !failure;
  }
  function choosePlan(id: string, checked: boolean) {
    const next = checked ? [...new Set([...plans, id])] : plans.filter(v => v !== id);
    setPlans(next);
    persist(saved.note, next, '虚拟观察预案已保存在本机。');
  }
  function branch(id: string, title: string, hint: string, children: ReactNode) {
    const open = !collapsed.includes(id);
    return <section className={`review-branch review-branch-${id}`} key={id} aria-label={title}>
      <div className="review-branch-side"><button onClick={() => toggleBranch(id)} aria-expanded={open} aria-controls={`review-branch-${id}`}><strong>{title}</strong><span>{hint} {open ? <DownOutlined /> : <PlusOutlined />}</span></button></div>
      <div id={`review-branch-${id}`} className="review-branch-content" hidden={!open}>{!['market', 'capital'].includes(id) && <div className="review-section-kind"><Tag color="orange">{hasReport ? `虚拟示例 · ${report.reviewDate}` : '待接入'}</Tag></div>}{children}</div>
    </section>;
  }
  return <div className="daily-review-page" style={colors}>
    <div className="daily-review-heading"><div><div className="review-breadcrumb">市场观察 / 每日复盘</div><h1>每日复盘 <Tag color="blue">行情与资金已接入</Tag></h1><p>梳理收盘结构，准备下一交易日</p></div><Button icon={<EditOutlined />} disabled={!hasReport} onClick={() => setNoteOpen(true)}>复盘笔记{hasReport && draft !== saved.note ? ' · 未保存' : ''}</Button></div>
    <div className="daily-review-scroll" ref={scroll} onScroll={e => { reading.scrollTop = e.currentTarget.scrollTop; }}>
      <Alert className="review-demo-notice" type="info" showIcon title="整体行情与资金流向读取真实归档 · 其余模块逐步接入" description="缺失字段显示“缺少数据来源”。其他四个分支仅在2026-07-31保留虚拟样例，均单独标注；笔记及预案仍属于该虚拟样例。" />
      <div className="daily-review-toolbar"><label className="review-date review-date-picker"><span>复盘日期</span><Input type="date" aria-label="复盘日期" value={selectedDate} min="0001-01-01" max="9999-12-31" onChange={e => { if (e.target.value && e.target.validity.valid) selectDate(e.target.value); }} /><strong>{new Date(`${selectedDate}T12:00:00`).toLocaleDateString('zh-CN', { weekday: 'short' })}</strong></label><Button aria-label="今天" onClick={() => selectDate(reviewToday())}>今天</Button><Button onClick={market.refresh} loading={market.loading}>刷新行情</Button>{market.data?.next_date && <><span className="review-date-arrow">→</span><span className="review-date"><span>准备交易日</span><strong>{market.data.next_date}</strong></span></>}{!hasReport && <Button type="link" onClick={() => selectDate(report.reviewDate)}>查看虚拟样例</Button>}</div>
      {hasReport && notice && <Alert className="review-save-notice" type={noticeType} title={notice} closable onClose={() => setNotice('')} />}
      <div className="daily-review-paper">
        <div className="review-map-heading"><div><span className="review-breadcrumb">A股市场情绪复盘 · 全景导图</span><h2>{selectedDate} 收盘复盘</h2><p>市场 → 资金 → 梯队 → 分歧 → 判断 → 下一交易日</p></div><Button type="link" onClick={() => { reading.collapsed = []; setCollapsed([]); }}>全部展开</Button></div>
        <div className="review-map">
          {branch('market', '整体行情', '真实收盘数据', <Market data={market.data} loading={market.loading} error={market.error} />)}
          {branch('capital', '资金流向', '主力与ETF', <Capital data={market.data} loading={market.loading} error={market.error} />)}
          {branch('ladder', '连板梯队', hasReport ? `${report.stocks.length}只虚拟连板` : '待接入', hasReport ? <Ladder report={report} onStock={setStock} /> : <span className="review-missing">缺少数据来源</span>)}
          {branch('promotion', '晋级断板', '同批次跟踪', hasReport ? <Promotion report={report} /> : <span className="review-missing">缺少数据来源</span>)}
          {branch('judgment', '核心判断', '示例推演', hasReport ? <Judgments report={report} /> : <span className="review-missing">缺少数据来源</span>)}
          {branch('plan', '次日观察', hasReport ? report.nextDate : '待接入', hasReport ? <Plans report={report} selected={plans} onChange={choosePlan} /> : <span className="review-missing">缺少数据来源</span>)}
        </div>
      </div>
      <footer className="daily-review-footer"><span>整体行情与资金流向读取真实归档 · 其他模块逐项接入</span><span>{hasReport ? '虚拟样例的笔记及预案仅保存在本机' : '缺值保留，按所选日期读取'}</span></footer>
    </div>
    <Modal open={!!stock} onCancel={() => setStock(undefined)} footer={<Button onClick={() => setStock(undefined)}>关闭详情</Button>} title={<span>{stock?.name} <Tag color="orange">虚拟数据</Tag></span>} className="daily-review-stock-modal" width={540}>
      {stock && <><p className="review-modal-caption">{report.reviewDate}收盘快照示例，尚未接入真实证券数据。</p><Descriptions column={2} bordered size="small" items={[
        { key: 'height', label: '连板高度', children: `${stock.height}板` }, { key: 'topic', label: '题材', children: stock.topic },
        { key: 'first', label: '首次封板', children: stock.firstSealed }, { key: 'order', label: '收盘封单', children: orderAmount(stock.orderWan) },
        { key: 'board', label: '板型', children: stock.boardType }, { key: 'next', label: '准备交易日', children: report.nextDate },
      ]} /><div className="review-modal-observation"><strong>下一交易日观察</strong><p>{stock.topic === 'AI应用' ? '关注能否晋级，以及同题材高位、中位与首板的承接。' : '关注持续性、接力情况与同方向个股表现。'}</p></div></>}
    </Modal>
    <Modal open={noteOpen} onCancel={() => setNoteOpen(false)} title={<span>{report.reviewDate}复盘笔记 <Tag color="orange">虚拟复盘</Tag></span>} className="daily-review-note-modal" width={640} footer={<><Button onClick={() => setNoteOpen(false)}>关闭并保留草稿</Button><Button type="primary" onClick={() => { if (persist(draft, plans, '虚拟复盘笔记及当前预案已保存在本机。')) setNoteOpen(false); }}>保存到本机</Button></>}>
      <p className="review-modal-caption">为{report.nextDate}交易前准备。保存后可跨启动保留；未保存草稿仅在本次客户端会话保留。</p>
      <label htmlFor="daily-review-note">判断、依据与下一交易日验证条件</label>
      <Input.TextArea id="daily-review-note" aria-label="复盘笔记内容" value={draft} maxLength={4000} showCount autoSize={{ minRows: 7, maxRows: 14 }} onChange={e => { setDraft(e.target.value); rememberDraft(report.id, e.target.value); }} />
      {noticeType === 'warning' && notice && <Alert type="warning" title={notice} style={{ marginTop: 16 }} />}
    </Modal>
  </div>;
}
