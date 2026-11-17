import { useState } from 'react';
import { Button, Modal, Tabs } from 'antd';
import { ArrowRightOutlined, DatabaseOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { dataSources, type DataSource } from './sourceDefinitions';
import './dataSources.css';

function SourcePanel({ source }: { source: DataSource }) {
  return <article className="source-panel" aria-label={`${source.label}数据来源`}>
    <div className="source-section-heading"><div><h3>{source.provider}</h3><p>{source.description}</p></div><span className="source-badge">{source.snapshot ? '归档 + Redis盘中' : '已归档数据'}</span></div>
    <div className="source-facts">
      <section><span className="source-caption">采集任务</span><strong>{source.task}</strong><code>{source.taskId}</code></section>
      <section><span className="source-caption">MySQL 业务表</span>{source.tables.map(table => <div className="source-table-name" key={table.name}><code>{table.name}</code><small>{table.role}</small></div>)}</section>
      <section><span className="source-caption">数据粒度与范围</span><strong>{source.grain}</strong><p>{source.scope}</p></section>
    </div>
    <div className="source-mapping-heading"><h4>指标与字段对应</h4><span>以下字段来自上方业务表，派生值在查询时计算</span></div>
    <div className="source-field-scroll"><table className="source-fields" aria-label={`${source.label}字段映射`}>
      <thead><tr><th scope="col">观察指标</th><th scope="col">数据库字段</th><th scope="col">取值 / 计算方式</th></tr></thead>
      <tbody>{source.rows.map(row => <tr key={row.metric}><th scope="row">{row.metric}</th><td><div className="source-field-codes">{row.fields.map(field => <code key={field}>{field}</code>)}</div></td><td>{row.method}</td></tr>)}</tbody>
    </table></div>
    {source.snapshot && <section className="source-live-panel" aria-label="Redis盘中来源">
      <h4>今日盘中 · Redis 最新快照</h4>
      <p>{source.snapshot.task} <code>{source.snapshot.taskId}</code></p>
      <p>Redis Hash：<code>{source.snapshot.key}</code> · 每品种仅保留最新一条，不写入日线表。</p>
      <p><code>latest</code> 为盘中报价；<code>source_time</code>、<code>source_update_time</code> 为两种来源时间，<code>observed_at</code> 为采样时间。均核对北京时间今天；来源时间不等于成交时刻。超过180秒标“过期”。</p>
      <p>今日缺归档时：当前值用最新报价；环比以最新报价对前条归档收盘计算；N期均值取最新报价与前N−1条归档收盘。后两者明确标为盘中估算，基准不足或异常时留空；历史计算仅使用归档日线。</p>
      <p>月历逐值标“Redis”，详情与导出保留来源时间、采样时间和盘中原价。插件停用、无今日快照或读取失败时保留归档结果，可刷新重试；刷新不会启动采集。</p>
    </section>}
    <div className="source-boundary"><InfoCircleOutlined /><div><strong>读取口径</strong>{source.notes.map(note => <p key={note}>{note}</p>)}</div></div>
  </article>;
}

export default function DataSources({ month, explanations }: { month: string; explanations: string[] }) {
  const [open, setOpen] = useState(false), [active, setActive] = useState('index');
  return <>
    <Button aria-label="来源与口径" type="text" size="small" icon={<InfoCircleOutlined />} onClick={() => { setActive('index'); setOpen(true); }}>来源与口径</Button>
    <Modal open={open} onCancel={() => setOpen(false)} centered width={1000} className="observation-source-modal"
      title={<div className="source-dialog-heading"><span className="source-dialog-icon"><DatabaseOutlined /></span><div><h2>数据来源与口径</h2><p>从采集来源、业务表到观察指标，逐项查看数据依据</p></div></div>}
      footer={<div className="source-dialog-footer"><span><i />归档数据 + 可用的今日Redis快照 · 刷新不会触发采集</span><Button onClick={() => setOpen(false)}>关闭</Button></div>}>
      <Tabs activeKey={active} onChange={setActive} tabBarGutter={26} items={[
        ...dataSources.map(source => ({ key: source.key, label: source.label, children: <SourcePanel source={source} /> })),
        { key: 'coverage', label: '当月覆盖', children: <article className="source-panel source-coverage" aria-label="当月覆盖说明">
          <div className="source-section-heading"><div><h3>{month} · 样本与覆盖</h3><p>对应当前选定月份及已应用指标，追加的历史月份不合并到这里。</p></div><span className="source-badge">{explanations.length} 项说明</span></div>
          {explanations.length ? <div className="source-coverage-list">{explanations.map((note, index) => <section key={note}><span>{String(index + 1).padStart(2, '0')}</span><p>{note}</p></section>)}</div>
            : <div className="source-coverage-empty"><InfoCircleOutlined /><h4>暂无当月覆盖说明</h4><p>当前没有可展示的样本或覆盖提示，不代表数据已经完整。</p></div>}
          <div className="source-boundary"><ArrowRightOutlined /><div><strong>如何更新数据</strong><p>月历查询归档结果及已有今日汇率快照。需要更新时，请在采集管理中找到对应标签页列出的采集任务，查看覆盖和运行状态，再刷新月历。</p></div></div>
        </article> },
      ]} />
    </Modal>
  </>;
}
