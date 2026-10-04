"""Seven independent historical products; no inferred OHLC or tick contracts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    title: str
    action: str
    field: str | None
    width: int
    requirement: str
    note: str


PRODUCTS = {
    'trend': Product('分时走势', 'GetStockTrend', 'trend', 5, 'intraday',
        '价格、均价、来源量与标记；不代表分钟 OHLC'),
    'auction': Product('开盘竞价', 'GetStockBid', 'bid', 4, 'opening_auction',
        '完整来源点序列；同分钟多点保留，源端无总点数'),
    'volume': Product('分钟成交量与成交额', 'GetStockVolTur', 'volumeturnover', 4, 'minute_volume',
        '来源分钟量额与标记；不提供每分钟 OHLC'),
    'trades': Product('分时成交明细', 'GetStockFenBi2', 'fb', 8, 'intraday_trades',
        '完整分笔数组及来源总数；不冒充交易所逐笔事件流'),
    'entrust': Product('分钟买卖委托汇总', 'GetStockBsvolume', 'bsentrust', 5, 'minute_entrust',
        '分钟买卖委托量额汇总；不含券商席位身份或逐笔委托撤单'),
    'large_order': Product('大单净额走势', 'GetStockDaDanTrend', 'dadanjinge', 2, 'large_order_trend',
        '来源大单净额可为负；不包含独立大单明细筛选'),
    'quote': Product('历史盘口与日行情摘要', 'GetStockPanKou', None, 0, 'historical_quote',
        '来源证券日盘口档位、行情、估值与股本摘要；不是全天秒级盘口回放'),
}


def project(kind):
    if kind not in PRODUCTS:
        raise ValueError('未知开盘啦数据类型')
    return 'kaipanla-' + kind.replace('_', '-')


def capability(kind):
    return 'kaipanla_' + kind + '.query'
