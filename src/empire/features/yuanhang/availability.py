"""Verified prelisting or initial-capital source gaps, never empty facts."""
from dataclasses import asdict, dataclass
from datetime import date

from empire.sources.listing_scope import download_listing_page
from empire.sources.yuanhang_history import IncompleteFinancialHistory, security_identity
from empire.sources.yuanhang_wire import EmptyHistoryResponse


@dataclass(frozen=True)
class DeferredSecurity:
    code: str
    listing_date: str | None
    through: str
    native_status: str = 'empty_history'
    status: str = 'deferred_prelisting'
    source_date: str | None = None
    node: str | None = None
    first_source_date: str | None = None
    point_count: int | None = None

    def evidence(self):
        result = dict(metadata_source='eastmoney_listing_scope', **asdict(self))
        if self.native_status == 'partial_total_circulating':
            result.update(missing_fields=[380], present_fields=[1, 402, 407])
        return result


async def resolve_empty(collector, code, through, *, reservation=None, cause=None, node=None):
    """One exact listing lookup after empty or validated partial native history."""
    security_identity(code)
    response = await download_listing_page(collector, 1, supplemental_symbol=code,
                                           profile='stocks', reservation=reservation)
    try:
        _, _, rows = await response.consume()
    finally:
        response.close()
    listed = rows[0][1]
    if listed is not None and listed <= date.fromisoformat(through):
        if (not collector.financial or not isinstance(cause, IncompleteFinancialHistory)
                or cause.code != code or cause.point_count != 1 or cause.source_date != listed):
            raise cause if cause is not None else EmptyHistoryResponse(1, 211 if collector.financial else 210)
        if await collector.query.has_history(code, financial=True):
            raise ValueError(code + ': 初始部分股本与已归档金融历史矛盾，保留断点') from cause
        return DeferredSecurity(code, listed.isoformat(), through, 'partial_total_circulating',
                                'deferred_initial_capital', listed.isoformat(), node,
                                cause.first_source_date.isoformat(), cause.point_count)
    if await collector.query.has_history(code, financial=collector.financial):
        raise ValueError(code + ': 上市前状态与已归档原生历史矛盾，不能作为空历史通过')
    return DeferredSecurity(code, listed.isoformat() if listed else None, through,
                            'partial_total_circulating' if cause is not None
                            and not isinstance(cause, EmptyHistoryResponse) else 'empty_history', node=node,
                            source_date=cause.source_date.isoformat() if isinstance(cause, IncompleteFinancialHistory) else None,
                            first_source_date=cause.first_source_date.isoformat() if isinstance(cause, IncompleteFinancialHistory) else None,
                            point_count=cause.point_count if isinstance(cause, IncompleteFinancialHistory) else None)
