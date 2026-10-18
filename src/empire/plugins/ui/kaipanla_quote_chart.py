"""Business price/average-price configuration on the shared exact-time canvas."""
from empire.plugins.ui.series_chart import SeriesChart


class QuoteChart(SeriesChart):
    def __init__(self, parent=None):
        super().__init__([dict(title='价格 / 均价（元）· 午休与缺分钟处断开',
                              fields=[(1, '价格'), (2, '均价')], positive=True)], parent)
        self.reference, self.message = None, '尚未查询分时走势'
        self.setAccessibleName('已归档分时价格及均价走势')

    def set_series(self, points, reference, message=''):
        self.reference, self.message = reference, message
        super().set_series(points, message)
