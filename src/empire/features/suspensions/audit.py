"""Business-owned suspensions.audit."""
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from empire.contracts.preparation import CheckEvidence
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.preparation.evidence import evidence
from empire.features.suspensions.contract import FIRST_DATE as SUSPENSION_FIRST_DATE
from empire.features.suspensions.coverage import coverage_as_of
from empire.plugins.infra.collection_state import read_state


def check_suspensions(plugin, confirmed=None):
    now = datetime.now(CHINA)
    with plugin.mysql.read_engine.connect() as conn:
        row = conn.execute(text('''
            SELECT COUNT(*) AS total,
              COUNT(DISTINCT unified_code,suspended_at,resume_key,record_key) AS identities,
              MIN(suspended_at) AS earliest,MAX(suspended_at) AS latest,
              SUM(RIGHT(unified_code,2) NOT IN ('SH','SZ') OR unified_code NOT REGEXP '^[0-9]{6}[.](SH|SZ)$'
                  OR suspension_type NOT IN ('full_day','intraday') OR TRIM(name)=''
                  OR resumed_at<suspended_at) AS bad,
              COUNT(DISTINCT RIGHT(unified_code,2)) AS markets
              , SUM(NOT source_dates_known OR NOT EXISTS (SELECT 1 FROM suspension_source_date d
                    WHERE d.unified_code=s.unified_code AND d.suspended_at=s.suspended_at
                    AND d.resume_key=s.resume_key AND d.record_key=s.record_key)) AS missing_dates
            FROM suspension_event s
        '''), {'source': plugin.source}).mappings().one()
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        try:
            cutoff, calendar_note = read_trade_day_cutoff(conn, now)
        except SQLAlchemyError:
            cutoff, calendar_note = None, '正式交易日历查询失败，不能推断交易日；字段与业务键检查仍独立呈现'
    coverage = state.get('coverage', {})
    if (confirmed and all(confirmed.get(k) == coverage.get(k) for k in ('from', 'through'))
            and confirmed.get('sql_confirmed_at', confirmed.get('confirmed_at')) == coverage.get('confirmed_at')):
        coverage = confirmed
    from_date, through = coverage.get('from'), coverage.get('through')
    complete = (state.get('collection_integrity_version') == 2
                and from_date == SUSPENSION_FIRST_DATE.isoformat()
                and cutoff is not None and through is not None and through >= cutoff.date().isoformat())
    total, bad = row['total'], (row['bad'] or 0) + (row['missing_dates'] or 0)
    stamp_status, stamp_note = coverage_as_of(coverage, now, cutoff)
    stamp = CheckEvidence('freshness', stamp_status, stamp_note, observed_at=coverage.get('confirmed_at', ''))
    complete &= stamp_status == 'pass'
    return (
        evidence('fields', total > 0 and not bad,
                 f'已存 {total} 条；市场、代码、类型、名称和日期异常 {row["bad"] or 0} 条；'
                 f'缺少来源日期 {row["missing_dates"] or 0} 条'),
        evidence('keys', total > 0 and total == row['identities'],
                 f'{total} 行，唯一业务键 {row["identities"]}；unified_code + suspended_at + resume_key + record_key'),
        CheckEvidence('coverage', 'pass' if complete else 'unknown' if cutoff is None or stamp_status == 'unknown' else 'fail',
                 f'来源起点 {SUSPENSION_FIRST_DATE}；SQL 连续覆盖 {from_date or "缺少"} ～ {through or "缺少"}；'
                 f'{calendar_note}；事件日期 {row["earliest"]} ～ {row["latest"]}；'
                 '更早历史属于来源限制，休市日或盘中未结束日期不作为已完成日要求'),
        evidence('quality', total > 0 and not bad and row['markets'] == 2,
                 f'字段异常 {bad}；已出现市场数 {row["markets"]}；复牌为空保持未知，临停单独分类'),
        stamp,
        evidence('temporal', total > 0 and not bad,
                 '按停牌和复牌生效时间保存；用于日频成交约束，不将原因文字作为事前信号'),
    )
