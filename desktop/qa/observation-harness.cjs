const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
app.setPath('userData', path.resolve(__dirname, '../../build/observation-qa-profile'));
const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../build/observation-fixture.json'), 'utf8'));
for (const metric of [
  {key:'market_amount',name:'沪深京成交额',category:'成交',unit:'元',scope:'equity_market'},
  {key:'financing_repayment_ratio',name:'融资买入/偿还比',category:'资金',unit:'%',scope:'market'},
  {key:'top_amount_share',name:'Top成交额占比',category:'成交',unit:'%',scope:'sample'},
  {key:'fx_USDCNH',name:'美元/人民币(离)收盘',category:'汇率',unit:'离岸人民币/美元',scope:'fx'},
]) if (!fixture.catalog.metrics.some(m=>m.key===metric.key)) fixture.catalog.metrics.push(metric);
for (const row of fixture.result.rows) {
  row.values.financing_repayment_ratio = row.status==='trade' ? '75.44' : null;
  row.values.top_amount_share = row.status==='trade' ? '41.46' : null;
  row.values.fx_USDCNH = row.date === '2024-02-04' ? null : '7.1234567891';
  row.values.financing_ratio_buy = row.status==='trade' ? '75' : null;
  row.values.financing_ratio_repayment = row.status==='trade' ? '100' : null;
}
let fail = false;
let historyFail = false;
let intradayStale = false;
global.observationReads = [];
global.liveReads = [];
global.catalogReads = 0;
global.liveFailure = false;
global.liveDelay = 30;
global.livePrice = '7.2234567891';
function monthRows(month) {
  const [year, number] = month.split('-').map(Number), first = new Date(Date.UTC(year, number - 1, 1));
  const start = new Date(first); start.setUTCDate(1 - (first.getUTCDay() + 6) % 7);
  const end = new Date(Date.UTC(year, number, 0)); end.setUTCDate(end.getUTCDate() + (7 - end.getUTCDay()) % 7);
  const trade = fixture.result.rows.find(r=>r.status==='trade');
  const today = new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  const rows = [];
  for (let day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    const date = day.toISOString().slice(0,10), isTrade = day.getUTCDay() > 0 && day.getUTCDay() < 6, future = date > today;
    const values = Object.fromEntries(Object.entries(trade.values).map(([k,v])=>[k, isTrade && !future ? v : null]));
    values.fx_USDCNH = future || date === '2024-02-04' ? null : '7.1234567891';
    values.market_amount = isTrade && !future ? '1485000000000.12345678' : null;
    const sources = date === today ? {fx_USDCNH: {source:'redis', latest:'7.1234567891', mode:'value', days:5,
      source_time:`${today}T14:30:00+08:00`, source_update_time:`${today}T05:59:00+08:00`,
      observed_at:`${today}T14:30:01+08:00`, sampling_stale:intradayStale}} : undefined;
    const live_basis = date === today ? {fx_USDCNH:{mode:'value', days:5, ready:true, total:'0'}} : undefined;
    rows.push({date,in_month:date.startsWith(month),status:isTrade?'trade':'closed',future,values,sources,live_basis});
  }
  return rows;
}
ipcMain.handle('read', async (_event, operation, params) => {
  if (operation === 'observation.catalog') { global.catalogReads++; return fixture.catalog; }
  if (operation === 'observation.live') {
    global.liveReads.push(params);
    const price = global.livePrice;
    await new Promise(resolve => setTimeout(resolve, global.liveDelay));
    if (global.liveFailure) throw Error('隔离Redis失败');
    const now = new Date().toISOString();
    return {date:params.date, values:{fx_USDCNH:price}, sources:{fx_USDCNH:{source:'redis',latest:price,mode:'value',days:5,
      source_time:now,source_update_time:now,observed_at:now,sampling_stale:false}}, warnings:[], queried_at:now};
  }
  if (operation === 'observation.read') {
    global.observationReads.push(params);
    if (fail) throw Error('隔离失败反例');
    if (historyFail && params.month === '2024-01') throw Error('隔离历史读取失败反例');
    await new Promise(resolve => setTimeout(resolve, params.month === '2024-01' ? 900 : 30));
    return {...fixture.result, ...params, rows:monthRows(params.month), warnings:['Top成交额占比：已归档个股样本（5574～5578只），不是全市场覆盖证明。']};
  }
  if (operation === 'tasks.list') return { rows: [], total: 0, categories: [] };
  return { rows: [], total: 0 };
});
ipcMain.handle('command', () => { throw Error('观察页面不应提交写命令'); });
ipcMain.handle('close', () => app.quit());
app.whenReady().then(() => {
  const window = new BrowserWindow({width:1600,height:1050,show:true,webPreferences:{
    preload:path.join(__dirname,'fixture-preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,
  }});
  window.webContents.session.on('will-download', (_event, item) => {
    item.setSavePath(path.resolve(__dirname, '../../build/observation-export.csv'));
    item.once('done', (_event, state) => { global.observationDownload = state; });
  });
  window.loadFile(path.resolve(__dirname,'../../build/observation-ui/index.html'));
});
global.setObservationFailure = value => { fail = value; };
global.setHistoryFailure = value => { historyFail = value; };
global.setIntradayStale = value => { intradayStale = value; };
