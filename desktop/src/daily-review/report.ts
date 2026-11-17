export type ReviewStock = {
  name: string; height: number; topic: string; firstSealed: string;
  orderWan: number; boardType: string;
};
export type ReviewPlan = { id: string; title: string; target: string; confirm: string; weaken: string };
export type ReviewReport = {
  id: string; dataKind: 'demo'; reviewDate: string; reviewDay: string;
  nextDate: string; nextDay: string; title: string;
  market: { firstBoards: number };
  stocks: ReviewStock[];
  firstThemes: { name: string; count: number; representatives: string }[];
  promotion: { secondYesterday: number; secondPromoted: string[]; firstYesterday: number; firstPromoted: string[]; failed: { name: string; topic: string; change: number }[]; formerHigh: { name: string; previousHeight: number; change: number } };
  judgments: { label: string; title: string; evidence: string }[];
  plans: ReviewPlan[];
};

// Virtual content for the four unfinished branches only; never a fallback for real facts.
export const demoReport: ReviewReport = {
  id: 'demo-2026-07-31', dataKind: 'demo', reviewDate: '2026-07-31', reviewDay: '周五',
  nextDate: '2026-08-03', nextDay: '周一', title: '普涨后的核心：AI能否形成持续主线',
  market: { firstBoards: 90 },
  stocks: [
    { name: '爱丽家居', height: 9, topic: '并购重组', firstSealed: '09:25', orderWan: 9244, boardType: '一字板' },
    { name: '传智教育', height: 5, topic: 'AI应用', firstSealed: '09:25', orderWan: 12200, boardType: '一字板' },
    { name: '一鸣食品', height: 4, topic: '食品饮料', firstSealed: '09:33', orderWan: 4910, boardType: '换手板' },
    { name: '高争民爆', height: 3, topic: '实控人变更', firstSealed: '09:30', orderWan: 8875, boardType: '换手板' },
    { name: '普联软件', height: 2, topic: 'AI应用', firstSealed: '09:50', orderWan: 12100, boardType: '换手板' },
    { name: '泛微网络', height: 2, topic: 'AI应用', firstSealed: '10:09', orderWan: 10800, boardType: '换手板' },
    { name: '税友股份', height: 2, topic: 'AI应用', firstSealed: '10:41', orderWan: 3519, boardType: '换手板' },
    { name: '香江控股', height: 2, topic: '算力', firstSealed: '11:06', orderWan: 411, boardType: '换手板' },
    { name: '神雾节能', height: 2, topic: 'ST摘帽', firstSealed: '09:25', orderWan: 4753, boardType: '一字板' },
    { name: '中国宝安', height: 2, topic: '锂电池', firstSealed: '11:15', orderWan: 1064, boardType: '换手板' },
  ],
  firstThemes: [
    { name: 'AI应用', count: 32, representatives: '蓝色光标、中文在线、易点天下（20cm）；福昕软件、昆仑万维、掌阅科技、用友网络、天娱数科等' },
    { name: '算力', count: 17, representatives: '润建股份、三维通信、利通电子、证通电子等' },
    { name: '机器人', count: 7, representatives: '中大力德、雷赛智能、锋龙股份、北特科技等' },
    { name: '芯片', count: 9, representatives: '太极实业（一字）、深桑达A、盛景微、东阳光等' },
    { name: '通信', count: 3, representatives: '泰晶科技、平安电工等' },
    { name: '地产链', count: 5, representatives: '京能置业、锦和商管、华天酒店、豪尔赛等' },
    { name: '并购重组', count: 8, representatives: '中岩大地、安德利等' },
    { name: '食品饮料', count: 5, representatives: '安记食品等' },
    { name: '其他', count: 4, representatives: '快意电梯、恒银科技、立航科技、肯特催化' },
  ],
  promotion: {
    secondYesterday: 11, secondPromoted: ['高争民爆'], firstYesterday: 44,
    firstPromoted: ['普联软件', '泛微网络', '税友股份', '香江控股', '神雾节能', '中国宝安'],
    failed: [
      { name: '返利科技', topic: 'AI应用', change: 5.59 }, { name: '金龙羽', topic: '固态电池', change: 4.53 },
      { name: '均瑶健康', topic: '食品', change: 1.47 }, { name: '海兴电力', topic: '智能电网', change: 0 },
      { name: '柳钢股份', topic: '钢铁', change: -1.67 },
    ],
    formerHigh: { name: '明新旭腾', previousHeight: 4, change: 5.34 },
  },
  judgments: [
    { label: '主线', title: 'AI应用有梯队纵深', evidence: '传智5板领涨；普联、泛微、税友2板承接；20cm首板提供弹性。' },
    { label: '切换', title: '半导体资金强，个股分歧', evidence: '兆易创新、德明利开板；观察硬件向软件的切换能否持续。' },
    { label: '风险', title: '梯队齐全不等于接力转强', evidence: '9板为独立重组逻辑，AI由5板传智带队；昨日2板晋级率仍低。' },
  ],
  plans: [
    { id: 'ai', title: 'AI应用分化', target: '传智教育5→6板；普联 / 泛微 / 税友2→3板', confirm: '高位继续走强，中位出现晋级，首板有次日溢价', weaken: '中位集中断板，首板缺少承接' },
    { id: 'chip', title: '半导体修复', target: '兆易创新、德明利开板后能否修复', confirm: '回流与个股修复同步，观察太极实业承接', weaken: '高开低走，板块再度分化' },
    { id: 'rotation', title: '科技轮动', target: '元件、通信设备的首板能否延续', confirm: '资金扩散同时出现个股晋级', weaken: '流入放缓，首板普遍低开' },
    { id: 'overseas', title: '外围验证', target: '交易前补看微软、纳指、SOX的7月31日收盘', confirm: '隔夜表现支持科技情绪', weaken: '隔夜回落削弱修复预期' },
  ],
};

export const number = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
export const signed = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${number(Math.abs(value))}`;
export const orderAmount = (wan: number) => wan >= 10000 ? `${number(wan / 10000)}亿` : `${number(wan)}万`;
export const percent = (count: number, total: number) => total > 0 ? `${(count / total * 100).toFixed(1)}%` : '—';
