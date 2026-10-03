"""Local, pinned request verification; network access stays in shared HTTP."""
import re
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36')


class ThsSession:
    def __init__(self):
        if QCoreApplication.instance() is None:
            raise RuntimeError('同花顺请求校验需要已初始化的 Qt 应用')
        self.engine = QJSEngine()
        script = Path(__file__).with_name('resources').joinpath('ths.js').read_text(encoding='utf-8')
        if self.engine.evaluate(script).isError():
            raise RuntimeError('同花顺本地请求校验初始化失败')

    def headers(self, referer):
        result = self.engine.evaluate('v()')
        token = result.toString()
        if result.isError() or not re.fullmatch(r'[A-Za-z0-9_-]{60}', token):
            raise RuntimeError('同花顺本地请求校验失败')
        return {'User-Agent': USER_AGENT, 'Referer': referer, 'Cookie': 'v=' + token}
