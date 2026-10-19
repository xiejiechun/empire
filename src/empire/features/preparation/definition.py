"""One definition per independently delivered output."""
from empire.contracts.preparation import Criterion, Requirement

SOURCE_POLICY = '一个来源即可独立满足本项，不要求多个网站相互印证。检查本来源的字段、重复、范围和明显错误。'
SCOPE_POLICY = ('按所选证券、市场和来源可提供的时间范围判断；列明覆盖起止和已知缺口。'
                '范围外、来源未提供的历史或可选信息不阻止范围内可用；范围内漏采和关键字段错误仍需处理。')
VERSION_POLICY = ('公告时间按来源实际精度保存，日频用途通常到日期即可；来源版本号、公告编号和完整旧版本历史不作通用门槛。'
                  '无来源编号可用稳定业务组合键，无来源版本号须声明内容比较和旧响应处理规则。'
                  '用于选股信号的财报、新闻等仍须说明何时可用；只有修订后数据时标明限制，不声称能严格还原当时信息。')


def requirement(ident, title, category, priority, purpose, grain, fields, key, coverage,
                quality, cadence, temporal, dependencies=(), *, kind="采集", boundary="", related=(), optional_fields=""):
    return Requirement(ident, title, category, priority, purpose, grain, fields, key, coverage,
        cadence, dependencies, (
            Criterion('fields', '字段与单位', fields, '检查必需字段和单位；可选字段未提供不影响本项通过'),
            Criterion('keys', '唯一键与重复', key + '；重复键为 0', '明确业务键，清查重复与版本冲突'),
            Criterion('coverage', '历史与对象覆盖', coverage, '补采声明范围内的漏采；来源不支持部分列为范围限制，无需另找网站证明'),
            Criterion('quality', '业务质量', quality, '修复数据或解析规则，并补充业务语义回归'),
            Criterion('freshness', '更新与时效', cadence, '验证最新成功核验时间与数据水位，恢复更新计划'),
            Criterion('temporal', '日期与使用范围', temporal, '检查本用途必要的日期，写明精度和使用限制；不强制完整修订历史'),
        ), kind, boundary or f"本项只负责：{title}。其他项目各自检查、各自计进度。", related, optional_fields)


R = requirement
