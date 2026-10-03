"""Explicit read-only security/date acceptance scope, independent of collection plans."""
import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PreparationScope:
    purpose: str = 'analysis'
    codes: tuple[str, ...] = ()
    start: str = ''
    end: str = ''

    @classmethod
    def parse(cls, value=None):
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) - {'purpose', 'codes', 'start', 'end'}:
            raise ValueError('数据检查范围格式无效')
        purpose = value.get('purpose', 'analysis')
        codes = value.get('codes', [])
        if purpose not in ('analysis', 'historical_signal'):
            raise ValueError('请选择数据分析或历史选股回测')
        if not isinstance(codes, (list, tuple)) or len(codes) > 100:
            raise ValueError('一次最多检查 100 个指定证券；留空检查当前股票池')
        if any(not isinstance(c, str) or not re.fullmatch(r'\d{6}', c, flags=re.ASCII) for c in codes):
            raise ValueError('证券代码须为六位数字，用逗号分隔')
        start, end = value.get('start', ''), value.get('end', '')
        for day in (start, end):
            if not isinstance(day, str):
                raise ValueError('日期须为 YYYY-MM-DD')
            if day:
                try:
                    parsed = date.fromisoformat(day)
                except ValueError:
                    raise ValueError('日期须为 YYYY-MM-DD') from None
                if parsed.isoformat() != day or parsed > date.today():
                    raise ValueError('日期格式无效或超过今天')
        if start and end and start > end:
            raise ValueError('起始日期不能晚于结束日期')
        return cls(purpose, tuple(sorted(set(codes))), start, end)

    def includes(self, day):
        return (not self.start or day >= self.start) and (not self.end or day <= self.end)

    def label(self):
        return ('数据分析 / 财务估值' if self.purpose == 'analysis' else '历史选股回测') + '；' + (
            '、'.join(self.codes) or '当前股票池全部证券') + '；日期 / 报告期 ' + (
            self.start or '来源最早') + ' ～ ' + (self.end or '来源最新') + '；按各数据必要字段检查'
