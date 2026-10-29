"""Prelisting deferral after verified native unavailability, never an empty fact."""
from dataclasses import asdict, dataclass
from datetime import date

from empire.sources.listing_scope import download_listing_page
from empire.sources.yuanhang_history import security_identity
from empire.sources.yuanhang_wire import EmptyHistoryResponse


@dataclass(frozen=True)
class DeferredSecurity:
    code: str
    listing_date: str | None
    through: str
    native_status: str = 'empty_history'

    def evidence(self):
        return dict(status='deferred_prelisting', metadata_source='eastmoney_listing_scope', **asdict(self))


async def resolve_empty(collector, code, through, *, reservation=None, cause=None):
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
        raise cause if cause is not None else EmptyHistoryResponse(1, 211 if collector.financial else 210)
    if await collector.query.has_history(code, financial=collector.financial):
        raise ValueError(code + ': 上市前状态与已归档原生历史矛盾，不能作为空历史通过')
    return DeferredSecurity(code, listed.isoformat() if listed else None, through,
                            'partial_total_circulating' if cause is not None
                            and not isinstance(cause, EmptyHistoryResponse) else 'empty_history')
