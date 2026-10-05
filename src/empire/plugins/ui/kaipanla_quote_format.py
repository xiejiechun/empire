"""Display-only quote fields; unknown quantities keep their source unit."""
import math

RED, GREEN, NEUTRAL = '#d9363e', '#168a3a', '#586477'

FIELDS = (
    ('open_px', '开盘', 'price'), ('high_px', '最高', 'price'), ('low_px', '最低', 'price'),
    ('turnover_ratio', '换手', 'percent'), ('total_turnover', '金额', 'compact'), ('amplitude', '振幅', 'percent'),
    ('avg_px', '均价', 'price'), ('total_amount', '成交量（来源单位）', 'compact'), ('vol_ratio', '量比', 'number'),
    ('up_px', '涨停', 'price'), ('down_px', '跌停', 'price'), ('entrust_rate', '委比', 'percent'),
    ('market_value', '总市值', 'compact'), ('circulation_value', '流通市值', 'compact'), ('pe_rate', '市盈率', 'number'),
    ('total_shares', '总股本', 'compact'), ('circulation_amount', '流通股本', 'compact'), ('dyn_pb_rate', '市净率', 'number'),
    ('actualcirculation_value', '实际流通市值', 'compact'), ('amount_in', '内盘（来源单位）', 'compact'),
    ('amount_out', '外盘（来源单位）', 'compact'),
)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def display(value, style='number'):
    if not number(value):
        return '—'
    if style == 'price':
        return f'{value:.2f}' if value > 0 else '—'
    if style == 'percent':
        return f'{value:.2f}%'
    if style == 'compact':
        for scale, suffix in ((1e8, '亿'), (1e4, '万')):
            if abs(value) >= scale:
                return f'{value / scale:.2f}{suffix}'
    return f'{value:,.2f}'.rstrip('0').rstrip('.')


def price_color(value, reference):
    if not number(value) or not number(reference) or value <= 0 or reference <= 0 or value == reference:
        return NEUTRAL
    return RED if value > reference else GREEN
