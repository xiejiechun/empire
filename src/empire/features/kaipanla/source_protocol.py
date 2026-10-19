"""Business-owned source_protocol; moved declarations retain existing behavior."""
import re
from datetime import date
from secrets import choice
from uuid import uuid4

URL = 'https://apphis.longhuvip.com/w1/api/index.php'


DOMAIN = 'longhuvip.com'


MODELS = ('PGBM10', 'SM-G9910', 'M2102K1C')


ACTION = {'trend': 'GetStockTrend', 'auction': 'GetStockBid'}


TREND_TIMES = tuple(
    f'{minute // 60:02d}:{minute % 60:02d}'
    for minute in (*range(570, 691), *range(781, 901))
)


class SourceError(ValueError):
    """An unsuccessful/ambiguous response must not advance collection coverage."""

    def __init__(self, message, *, category='invalid_fields', details=None):
        super().__init__(message)
        self.category, self.details = category, details or {}


def request_options(code, day, kind):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('开盘啦证券代码必须为六位数字')
    if not isinstance(day, date) or day < date(2021, 1, 1):
        raise ValueError('开盘啦历史范围从 2021-01-01 开始')
    if kind not in ACTION:
        raise ValueError('开盘啦请求类型无效')
    # Called by the shared downloader on every transport attempt, including retries.
    return dict(data=dict(c='StockL2History', a=ACTION[kind], StockID=code,
        Day=day.isoformat(), apiv='w44', PhoneOSNew='1', PhoneOS='1',
        DeviceID=str(uuid4()), VerSion='5.23.0.4'), headers={
        'User-Agent': f'Dalvik/2.1.0 (Linux; U; Android 12; {choice(MODELS)} Build/SP1A.210812.016)'})
