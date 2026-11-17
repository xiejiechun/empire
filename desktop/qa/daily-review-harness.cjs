const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
app.setPath('userData', path.resolve(__dirname, '../../build/daily-review-profiles', randomUUID()));
global.reviewReads = [];
global.reviewWrites = [];
global.marketRequests = [];
global.marketDelays = {};
global.marketFailNext = false;
global.capitalEmpty = false;
global.sectorUncovered = false;
ipcMain.handle('read', async (_event, operation, params) => {
  global.reviewReads.push(operation);
  if (operation === 'tasks.list') return { rows: [], total: 0, categories: [] };
  if (operation === 'review.market') {
    global.marketRequests.push(params.date);
    if (global.marketFailNext) { global.marketFailNext = false; throw Error('fixture read failure'); }
    await new Promise(resolve => setTimeout(resolve, global.marketDelays[params.date] || 0));
    const ready = ['2026-11-13', '2026-11-12', '2026-07-31'].includes(params.date);
    return { date: params.date, status: ready ? 'closed' : params.date === '2026-11-15' ? 'rest' : 'unknown',
      queried_at: '2026-11-15T18:00:00+08:00', previous_date: ready ? (params.date === '2026-07-31' ? '2026-07-30' : '2026-11-12') : null, next_date: ready ? (params.date === '2026-07-31' ? '2026-08-03' : '2026-11-16') : null,
      limit_up: ready ? 38 : null, limit_down: ready ? 0 : null, first_boards: ready ? 31 : null, chain: ready ? 7 : null,
      amount_yuan: ready ? '1667073597654.70' : null, amount_change_yuan: ready ? '-278795011721.9' : null,
      price_count: ready ? 5571 : 0, previous_price_count: ready ? 5572 : 0,
      main_flow_yuan: ready ? global.capitalEmpty ? '0' : '-136825392355' : null, advance: ready ? 734 : null, decline: ready ? 4594 : null, flat: ready ? 50 : null, fund_count: ready ? 5378 : 0,
      capital: { sectors: { inflow: ready && !global.sectorUncovered ? global.capitalEmpty ? [] : [{ industry_code: '881001', name: '完整行业流入', amount_yuan: '987654321', member_count: 42, covered_count: 42 }] : null,
        outflow: ready && !global.sectorUncovered ? global.capitalEmpty ? [] : [{ industry_code: '881002', name: '部分行业流出', amount_yuan: '-876543210', member_count: 100, covered_count: 98 }] : null,
        basis_observed_at: ready ? '2026-11-14T12:00:00+00:00' : null, industry_count: ready ? 3 : 0, complete_count: ready && !global.sectorUncovered ? 1 : 0, partial_count: ready && !global.sectorUncovered ? 1 : 0, uncovered_count: ready ? global.sectorUncovered ? 3 : 1 : 0, issue: ready && global.sectorUncovered ? '所选日资金榜未覆盖当前行业成分' : '' }, visible_flow_yuan: ready ? '0' : null, dark_flow_yuan: ready ? global.capitalEmpty ? '0' : '-136825392355' : null,
        inflow: ready ? global.capitalEmpty ? [] : [{ unified_code: '600000.SH', name: '真实查询夹具流入', amount_yuan: '123456789', change_ratio: '0.0123' }] : null,
        outflow: ready ? global.capitalEmpty ? [] : [{ unified_code: '000001.SZ', name: '真实查询夹具流出', amount_yuan: '-234567890', change_ratio: '-0.0234' }] : null },
      indices: ['上证指数', '深证成指', '科创50', '创业板指', '沪深300', '北证50'].map((name, i) => ({ name, code: null, close: ready && i < 5 ? '4000' : null, change: ready && i < 5 ? '-1.25' : null })),
      overseas: ['日经225', '韩国综合', '纳斯达克', 'SOX', '微软'].map(name => ({ name, close: null, change: null })), issues: [] };
  }
  throw Error('未知后端读取：' + operation);
});
ipcMain.handle('command', (_event, operation) => {
  global.reviewWrites.push(operation);
  throw Error('虚拟复盘不应发送后端写命令');
});
ipcMain.handle('close', () => app.quit());
app.whenReady().then(() => {
  const window = new BrowserWindow({ width: 1500, height: 1050, show: true, webPreferences: {
    preload: path.join(__dirname, 'fixture-preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, backgroundThrottling: false,
  } });
  window.loadFile(path.resolve(process.env.EMPIRE_REVIEW_QA_DIST || path.resolve(__dirname, '../../build/daily-review-ui'), 'index.html'));
});
