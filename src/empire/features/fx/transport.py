"""All forex transport uses the shared downloader and admission controls."""
import hashlib
from datetime import UTC, datetime

from empire.features.fx.contract import DAILY_PROJECT, LIVE_PROJECT, url
from empire.features.fx.source import (
    DailyQuoteUnavailable,
    QuoteUnavailable,
    annual,
    candle,
    current_candle,
    realtime,
    recent,
)
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


class Transport:
    async def fetch(self, code, unit='last', snapshot=None, *, reservation=None, raw_annual=False):
        await wait_for_capacity(self.ingest, self.stats)
        observed = datetime.now(UTC)
        response = await self.http.request('GET', url(code, unit),
            allowed_domains=('10jqka.com.cn',), headers={'Referer': 'https://fe.10jqka.com.cn/'},
            project_id=self.project_id, policy=self.http.response_policy('generic'),
            reservation=reservation, max_retries=self.request_retries)
        async def consume():
            try:
                body = response.content.decode('utf8')
                if unit == 'live':
                    return realtime(body, code, observed)
                if unit == 'today':
                    return current_candle(body, code, observed)
                if unit == 'last':
                    return recent(body, code, observed), observed
                if raw_annual:
                    return candle(body, code, unit)[1]
                return annual(body, code, unit, snapshot)
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                if (isinstance(exc, QuoteUnavailable) and self.project_id == LIVE_PROJECT
                        or isinstance(exc, DailyQuoteUnavailable) and self.project_id == DAILY_PROJECT):
                    raise
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats,
                    self.project_id, exc, stage='source_validation',
                    unavailable_message='汇率来源错误样本暂不可用',
                    fields=dict(request_url=url(code, unit), status_code=response.status_code,
                        raw_body=raw[:65536], observed_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest()))
                raise
            finally:
                if reservation is None:
                    response.close()
        if reservation is not None:
            deferred = DeferredResponse(response, consume)
            deferred.owner = reservation.owner
            return deferred
        return await consume()
