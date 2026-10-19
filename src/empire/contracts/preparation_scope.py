"""Explicit read-only security/date acceptance scope, independent of collection plans."""
import re
from dataclasses import dataclass
from datetime import date

STUDIES = {'factor': '因子研究', 'backtest': '策略回测', 'value': '长期价值研究'}
FOCUSES = {
    'factor': {'price': '量价 / 动量 / 波动', 'valuation': '价值 / 规模 / 股息',
               'quality': '盈利质量 / 成长', 'holders': '股东 / 风险事件', 'flows': '资金流'},
    'backtest': {'price': '量价策略', 'valuation': '价值策略', 'quality': '质量 / 成长策略',
                 'holders': '股东 / 事件策略', 'flows': '资金流策略'},
    'value': {'operating': '经营 / 财务趋势', 'valuation': '估值与股息',
              'returns': '股东回报 / 稀释', 'risk': '治理 / 资本使用风险'},
}


@dataclass(frozen=True)
class PreparationScope:
    purpose: str = 'analysis'
    codes: tuple[str, ...] = ()
    start: str = ''
    end: str = ''
    index_codes: tuple[str, ...] = ()
    study: str = ''
    focus: str = ''
    scan: str = 'all'

    @classmethod
    def parse(cls, value=None, *, allow_future=False):
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) - {'purpose', 'codes', 'start', 'end', 'index_codes', 'study', 'focus', 'scan'}:
            raise ValueError('数据检查范围格式无效')
        purpose = value.get('purpose', 'analysis')
        study, focus, scan = (value.get(k, default) for k, default in
                              (('study', ''), ('focus', ''), ('scan', 'all')))
        if (not isinstance(study, str) or study and study not in STUDIES
                or not isinstance(focus, str) or study and focus not in FOCUSES[study]
                or not study and focus or scan not in ('all', 'research')):
            raise ValueError('研究用途、方向或扫描方式无效')
        if study:
            required_purpose = 'analysis' if study == 'value' else 'historical_signal'
            if 'purpose' in value and purpose != required_purpose:
                raise ValueError('研究用途与信息可用日期规则不一致')
            purpose = required_purpose
        codes = value.get('codes', [])
        if purpose not in ('analysis', 'historical_signal'):
            raise ValueError('请选择数据分析或历史选股回测')
        if not isinstance(codes, (list, tuple)) or len(codes) > 100:
            raise ValueError('一次最多检查 100 个指定证券；留空检查当前股票池')
        if any(not isinstance(c, str) or not re.fullmatch(r'\d{6}', c, flags=re.ASCII) for c in codes):
            raise ValueError('证券代码须为六位数字，用逗号分隔')
        indices = value.get('index_codes', [])
        if (not isinstance(indices, (list, tuple)) or len(indices) > 100 or
                any(not isinstance(c, str) or not re.fullmatch(r'[0-9A-Z]{6}', c) for c in indices)):
            raise ValueError('指数须为同花顺六位代码，例如1A0001；一次最多100项')
        start, end = value.get('start', ''), value.get('end', '')
        for day in (start, end):
            if not isinstance(day, str):
                raise ValueError('日期须为 YYYY-MM-DD')
            if day:
                try:
                    parsed = date.fromisoformat(day)
                except ValueError:
                    raise ValueError('日期须为 YYYY-MM-DD') from None
                if parsed.isoformat() != day or not allow_future and parsed > date.today():
                    raise ValueError('日期格式无效或超过今天')
        if start and end and start > end:
            raise ValueError('起始日期不能晚于结束日期')
        return cls(purpose, tuple(sorted(set(codes))), start, end, tuple(sorted(set(indices))), study, focus, scan)

    def includes(self, day):
        return (not self.start or day >= self.start) and (not self.end or day <= self.end)

    def label(self):
        study = f'{STUDIES[self.study]} / {FOCUSES[self.study][self.focus]}；' if self.study else ''
        return study + ('数据分析 / 财务估值' if self.purpose == 'analysis' else '历史选股回测') + '；' + (
            '、'.join(self.codes) or '当前股票池全部证券') + '；日期 / 报告期 ' + (
            self.start or '来源最早') + ' ～ ' + (self.end or '来源最新') + '；指数：' + (
            '、'.join(self.index_codes) or '来源指数目录') + '；按各数据必要字段检查；' + (
            '本次研究必需项' if self.scan == 'research' else '全部项目')
