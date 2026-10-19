"""Product-specific series semantics on the shared native canvas."""
from empire.plugins.ui.series_chart import SeriesChart


def product_chart(kind):
    specifications = {
        'trades': [dict(title='当前明细页价格（元）· 横轴为原始来源序号，不代表全日或完整时间窗',
                       fields=[(1, '价格')], sequence=True, positive=True)],
        'trend': [dict(title='价格 / 均价（元）· 午休及缺分钟处断开，零占位不画有效价', fields=[(1, '价格'), (2, '均价')], positive=True),
                  dict(title='来源量（来源单位）', fields=[(3, '来源量')], bars=True, zero=True)],
        'auction': [dict(title='竞价价格（元）· 横轴为来源序号，同分钟多点保留', fields=[(1, '价格')], sequence=True, positive=True),
                    dict(title='竞价来源量（来源单位，未解码匹配口径）', fields=[(3, '来源量')], bars=True, zero=True, sequence=True)],
        'volume': [dict(title='分钟成交量（来源单位）', fields=[(1, '成交量')], bars=True, zero=True),
                   dict(title='分钟成交额（来源单位）', fields=[(2, '成交额')], bars=True, zero=True)],
        'entrust': [dict(title='买卖委托量（来源单位）· 蓝买 / 橙卖', fields=[(1, '买委托量'), (2, '卖委托量')], zero=True),
                    dict(title='买卖委托额（来源单位）· 蓝买 / 橙卖', fields=[(3, '买委托额'), (4, '卖委托额')], zero=True)],
        'large_order': [dict(title='来源大单净额（来源单位）· 保留正负，不再次累加', fields=[(1, '大单净额')], zero=True)],
    }
    return SeriesChart(specifications[kind])
