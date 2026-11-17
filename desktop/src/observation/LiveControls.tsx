import { Button, InputNumber, Switch, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { sourceTime } from './model';
import type { useLiveRefresh } from './useLiveRefresh';

export default function LiveControls({ live }: { live: ReturnType<typeof useLiveRefresh> }) {
  const count = Object.keys(live.sources).length;
  const stale = Object.values(live.sources).some(s => s.sampling_stale);
  const status = live.error || (stale ? '采样过期' : count ? `${count}项盘中` : live.eligible ? '等待报价' : '无今日盘中项');
  return <div className="observation-live-controls" aria-label="Redis盘中刷新">
    <Tooltip title={`${live.error || ''} 仅刷新今日Redis盘中值，不重载日历。${live.updatedAt ? `最近读取 ${sourceTime(live.updatedAt)}。` : ''}历史和已有归档保持不变；更新归档基准请点击“刷新数据”。`}>
      <span className={`redis-status ${stale || live.error ? 'is-stale' : ''}`} role="status"><i />Redis <small>{status}</small></span>
    </Tooltip>
    <label>自动刷新 <Switch size="small" aria-label="自动刷新Redis" checked={live.enabled} onChange={live.setEnabled} /></label>
    <InputNumber aria-label="Redis刷新间隔秒" min={1} max={3600} precision={0} value={live.seconds} onChange={value => { if (value != null && value >= 1 && value <= 3600) live.setSeconds(Math.round(value)); }} suffix="秒" />
    <Tooltip title="立即刷新Redis盘中数据"><Button aria-label="刷新Redis" type="text" icon={<ReloadOutlined />} loading={live.loading} disabled={!live.eligible} onClick={live.refresh} /></Tooltip>
  </div>;
}
