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


class ThsDirectorySession:
    """Pinned 1.7 directory protocol in a network-free JavaScript environment."""

    def headers(self, referer):
        if QCoreApplication.instance() is None:
            raise RuntimeError('同花顺请求校验需要已初始化的 Qt 应用')
        engine = QJSEngine()
        shim = '''
var window = this;
var location = {protocol:'https:',host:'q.10jqka.com.cn',hostname:'q.10jqka.com.cn',
 href:'https://q.10jqka.com.cn/',pathname:'/',port:''};
var navigator = {userAgent:'Mozilla/5.0',appVersion:'5.0 (Windows)',platform:'Win32',
 vendor:'Google Inc.',language:'zh-CN',languages:['zh-CN','zh'],plugins:[],
 javaEnabled:function(){return false}};
function noop() {}
function element() {return {appendChild:noop,insertBefore:noop,addEventListener:noop,
 getContext:function(){return null}}}
var document = {cookie:'',documentElement:element(),body:element(),head:element(),
 createElement:element,getElementsByTagName:function(){return []},addEventListener:noop};
var localStorage = {getItem:function(){return null},setItem:noop,removeItem:noop};
var addEventListener=noop,setTimeout=noop,setInterval=noop,Element=function(){};
'''
        script = Path(__file__).with_name('resources').joinpath('ths_directory.js').read_text(encoding='utf-8')
        script, count = re.subn(r'^var TOKEN_SERVER_TIME=[0-9.]+;',
                               'var TOKEN_SERVER_TIME=Date.now()/1000;', script, count=1)
        if count != 1 or engine.evaluate(shim).isError() or engine.evaluate(script).isError():
            raise RuntimeError('同花顺股票目录请求校验初始化失败')
        cookie = engine.evaluate('document.cookie').toString().split(';', 1)[0]
        if not re.fullmatch(r'v=[A-Za-z0-9_-]{60}', cookie):
            raise RuntimeError('同花顺股票目录请求校验失败')
        return {'User-Agent': 'Mozilla/5.0', 'Referer': referer, 'Cookie': cookie}
