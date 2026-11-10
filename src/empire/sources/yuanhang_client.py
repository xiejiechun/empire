"""Node-bound guest provisioning, login and native history over shared routing."""
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from urllib.parse import urlencode

from empire.sources.yuanhang_auth import (
    AUTH_POLICY,
    AuthenticationError,
    _item,
    exchange_frame,
    login_guest,
    login_native,
)
from empire.sources.yuanhang_history import (
    IncompleteFinancialHistory,
    MissingFinancialValue,
    history_query,
    normalize_daily,
    normalize_financial,
    security_identity,
)
from empire.sources.yuanhang_identity import GuestIdentity
from empire.sources.yuanhang_wire import EmptyHistoryResponse, decode_response


async def provision_guest(http, registry, code, *, project_id):
    """Exactly one initial application per durable profile; never retry a refusal.

    Mark intent before sending. Unknown outcomes stay blocked for investigation,
    including cancellation, process loss and SQL failure after account issuance.
    """
    profiles = await registry.load()
    profile = profiles.get(code)
    if profile is None:
        raise ValueError('节点身份档案尚未保存')
    if profile.provisioned:
        return profile
    if profile.registration != 'unrequested':
        raise ValueError('节点已有申请或拒绝记录；不重复申请、不轮换标识')
    profile = await registry.transition(code, 'unrequested', 'requested')
    try:
        query = urlencode(profile.creation['params'])
        response = await http.request(profile.creation['method'], profile.creation['endpoint'] + '?' + query,
            allowed_domains=('10jqka.com.cn',), project_id=project_id, sensitive=True,
            max_redirects=0, max_retries=0, total_timeout=30, policy=AUTH_POLICY, proxy_code=code)
        try:
            item = _item(response.content, 'guest-application')
            identity = GuestIdentity(item.get('account', ''), item.get('passwd', ''))
        finally:
            response.close()
        return await registry.bind(code, identity, profile.device)
    except AuthenticationError as exc:
        await registry.transition(code, 'requested', 'rejected' if exc.code is not None else 'unknown',
                                  rejection_code=exc.code)
        raise
    except Exception:
        await registry.transition(code, 'requested', 'unknown')
        raise


async def login_profile(http, profile, *, project_id):
    if not profile.provisioned:
        raise ValueError('节点尚未取得游客账号，不能借用其他节点身份')
    return await login_guest(http, profile.identity, profile.device,
                             project_id=project_id, proxy_code=profile.code)


@dataclass(frozen=True)
class HistorySnapshot:
    native_market: str
    observed_at: datetime
    data: object
    response_bytes: int = 0
    decoded_bytes: int = 0


@dataclass(frozen=True)
class DecodedHistory:
    data: object
    response_bytes: int
    decoded_bytes: int


async def fetch_history(http, session, *, unified_code, dataset, start, end, instance=1,
                        max_retries=2, native_market=None, reservation=None, fresh_connection=False):
    if session.proxy_code is None:
        raise ValueError('节点行情请求必须使用已绑定设备的登录会话')
    preferred = security_identity(unified_code, native_market)[:4]
    markets = [preferred]
    if unified_code.endswith('.SH'):
        markets.append('USHT' if preferred == 'USHA' else 'USHA')
    for market in markets:
        observed = datetime.now(UTC)
        try:
            data = await _fetch_market(http, session, unified_code=unified_code, dataset=dataset,
                start=start, end=end, instance=instance, max_retries=max_retries,
                native_market=market, reservation=reservation, fresh_connection=fresh_connection)
        except EmptyHistoryResponse:
            if market == markets[-1]:
                raise
        else:
            if isinstance(data, DecodedHistory):
                return HistorySnapshot(market, observed, data.data, data.response_bytes, data.decoded_bytes)
            return HistorySnapshot(market, observed, data)


async def _fetch_market(http, session, *, unified_code, dataset, start, end, instance,
                        max_retries, native_market, reservation, fresh_connection=False):
    query = history_query(unified_code=unified_code, dataset=dataset, start=start, end=end,
                          instance=instance, native_market=native_market)
    policy = http.response_policy('stocks')

    async def exchange(channel):
        if not channel.state.get('yuanhang_authenticated'):
            await login_native(channel, session)
            channel.state['yuanhang_authenticated'] = True
        return await exchange_frame(channel, query, allow_idle=True)

    response = await http.request_stream(session.servers[0], exchange, policy=policy,
                                         proxy_code=session.proxy_code, max_retries=max_retries,
                                         reservation=reservation, connection_key=session,
                                         fresh_connection=fresh_connection)
    tables = ()
    try:
        tables = decode_response(response.content, instance=instance,
                                 request_id=210 if dataset == 'daily' else 211,
                                 limit=policy.max_body_bytes, reserve=response.reserve_decoded)
        normalizer = {'daily': normalize_daily, 'financial': normalize_financial}[dataset]
        data = normalizer(tables, unified_code=unified_code, start=start, end=end, native_market=native_market)
        return DecodedHistory(data, len(response.content), sum(t['decoded_bytes'] for t in tables))
    except MissingFinancialValue as exc:
        # 211 contains business tables only; retain a bounded structural proof,
        # never authentication tokens, endpoints or the full successful history.
        exc.yuanhang_diagnostics = dict(node=session.proxy_code, security=unified_code,
            native_market=native_market, field=exc.field, source_date=str(exc.day),
            fresh_connection=fresh_connection, response_bytes=len(response.content),
            response_sha256=hashlib.sha256(response.content).hexdigest(),
            null_tables=[dict(version=t['version'], row_count=t['row_count'],
                descriptor=next(list(d) for d in t['fields'] if d[0] == exc.field),
                null_dates=list(islice((r[1] for r in t['rows'] if r.get(exc.field) is None), 8)))
                for t in islice((t for t in tables if any(d[0] == exc.field for d in t['fields'])), 3)])
        raise
    except (EmptyHistoryResponse, IncompleteFinancialHistory):
        raise
    except ValueError as exc:
        raise ValueError(f'{unified_code}/{dataset}/{native_market}: {exc}') from exc
    finally:
        response.close()
