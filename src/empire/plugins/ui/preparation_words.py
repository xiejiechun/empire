"""Plain-language presentation of the existing checks; does not decide readiness."""
STATUS = {'已验收': '已准备好', '未开发': '还没开发', '有失败项': '还有问题', '待验收': '还需检查'}
PRIORITY = {'核心': '先准备这些', '研究': '深入分析用', '扩展': '按需要添加'}
CHECKS = {
    'task': ('采集功能做好了吗', '软件里有对应的采集任务，能找到负责采集的功能。', '把这类数据的采集功能做好，并加入采集任务。'),
    'dataset': ('数据保存功能做好了吗', '知道数据该存到哪里，重复数据不乱存，旧数据不会盖掉新数据。', '补齐数据保存、去重和新旧数据处理功能。'),
    'query': ('能查看和检查数据吗', '有查看数据的功能，也有逐条检查数据是否齐全的功能。', '补齐数据查询和自动检查功能。'),
    'source_tests': ('采集功能测试过了吗', '当前版本的采集测试已全部通过，包括漏页、中断和异常返回。', '补齐采集测试，再运行完整检查。'),
    'archive_tests': ('数据保存测试过了吗', '重复采集、数据修正、旧数据重来和保存失败等情况都测试通过。', '测试数据能否正确保存，以及出错后能否重试。'),
    'shared_tests': ('和其他功能配合正常吗', '和其他任务一起使用、暂停、恢复和处理失败等情况都测试通过。', '运行完整检查，确认不会影响其他采集任务。'),
    'fields': ('必需的信息齐不齐', '', '补齐必需信息并检查单位；可选信息缺少不影响通过。'),
    'keys': ('有没有重复记录', '', '查清重复记录，保证同一条数据不会重复算。'),
    'coverage': ('声明范围内有没有漏采', '', '补齐范围内漏采；来源不提供的范围写明限制，不要求另找网站印证。'),
    'quality': ('内容有没有明显错误', '', '修正内容错误，并增加检查，避免再次出错。'),
    'freshness': ('有没有及时更新', '', '检查最近更新情况，恢复采集；区分来源没更新和软件没采到。'),
    'temporal': ('日期和用途是否说清楚', '', '检查本用途必要的日期和使用限制；不强制精确到秒或补齐全部旧版本。'),
}
REPLACEMENTS = {
    '未接入数据检查插件': '这类数据的自动检查还没做好',
    '检查器尚未提供本验收项的证据': '这一项还没有检查结果，需要补上检查功能',
    '查询插件未运行或结构校验失败；在插件管理检查依赖': '数据暂时读不到，请在插件管理中查看相关功能是否正常',
    '查询失败、超时或证据无效；本轮不能确认，请检查插件与数据库后重试': '这次没查成功，暂时不能确定，请检查相关功能和数据库后重试',

    '当前 A 股证券列表': '现在有哪些 A 股股票',
    '上市、退市与证券沿革': '股票上市、退市和更名记录',
    '板块与证券类型沿革': '股票所属板块和类型的变化',
    '历史可知版本': '过去各个时间能看到的内容',
    '收益口径': '收益怎么算',
    '原始及后续修订的可知内容': '修改前后分别公开了什么内容',
    '历史 PIT 未实现': '还不能还原当时看到的新闻',
    '当前 finance_news 更新来源修订但不保留旧正文': '新闻内容更新后，之前的正文没有保留下来',
    '缺源端总量/断档台账': '缺少来源的总条数和漏采时间段记录',
    '仅最新版本键': '目前只保留每条新闻的最新内容',
    '复权因子': '复权因子（抵消分红送股对股价的影响）',

    'source_symbol': '来源网站的股票代码', 'unified_code': '统一股票代码',
    'updated_at': '内容更新时间', 'is_trade': '是否交易', 'trade_date': '日期',
    'source +': '来源 +', 'source、': '来源、', 'code(六位)': '六位股票代码',
    'name、': '股票名称、', 'market(SH/SZ/BJ)': '上海/深圳/北京市场',
    'publication': '完整列表的保存记录', 'row_count': '记录数量',
    'source_updated_at': '来源修改时间', 'source + news_id': '来源 + 新闻编号',
    'news_id': '新闻编号', 'version_observed_at': '当前版本首次看到的时间',
    'first_seen_at': '首次采到的时间', 'published_at': '发布时间',
    'SQL': '数据库', 'Redis': '临时缓存', 'JSON': '结构化', 'PIT': '历史信息还原',
    'OHLC': '开盘价、最高价、最低价、收盘价', 'vintage': '当时公布的版本',
    'capability': '功能', 'schema': '数据格式', '归档': '保存', '核验': '检查',
    '业务键': '识别同一条记录的依据', '唯一键': '识别同一条记录的依据',
    '上界': '最近确认时间', '水位': '更新到的日期', '口径': '计算方式',
    '时效': '更新是否及时', '可知时间': '当时能看到这条信息的时间',
    '时点': '时间', '修订': '修改', '披露': '公布', '存续': '上市交易',
    '规范化': '统一格式', '结构化证券关联': '这条消息对应哪些股票',
    '证券关联': '对应股票', '证券 ID': '股票编号', '公司 ID': '公司编号',
    '回归': '重新测试', '完整发布': '完整保存的列表',
    '空正文/标题/非法分类标记': '正文、标题或分类有问题',
    '异常超前': '不合理地晚于当前时间',
}


def plain(text):
    for old in sorted(REPLACEMENTS, key=len, reverse=True):
        text = text.replace(old, REPLACEMENTS[old])
    return text


def check_title(item):
    if item.get('kind', '采集') != '采集' and item['id'] in {'task', 'source_tests'}:
        return '这项处理功能做好了吗' if item['id'] == 'task' else '这项处理功能测试过了吗'
    return CHECKS.get(item['id'], (plain(item['title']), '', ''))[0]


def expected(item):
    if item.get('kind', '采集') != '采集' and item['id'] in {'task', 'source_tests'}:
        return plain(item['expected'])
    return CHECKS.get(item['id'], ('', '', ''))[1] or plain(item['expected'])


def action(item):
    if item.get('recommended_action'):
        return item['recommended_action']
    if item.get('kind', '采集') != '采集' and item['id'] in {'task', 'source_tests'}:
        return plain(item['action'])
    return CHECKS.get(item['id'], ('', '', plain(item['action'])))[2]


def finding(item):
    if item['phase'] != '开发':
        return plain(item['measured'])
    if item['status'] == 'pass':
        return '这一步已检查通过。具体记录可在“详细检查记录”中查看。'
    if item['status'] == 'fail':
        return '这一步还没接好，需要继续开发。'
    if item['measured'].startswith('未接入'):
        return '还没有对应功能，等待开发。'
    return '还没有当前版本全部测试通过的记录。之前的结果不能代替这次检查。'
