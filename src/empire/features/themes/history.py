"""Atomic Redis-only day baselines and deltas; no collector/archive registration yet."""
import json
from datetime import datetime, timedelta

from redis.exceptions import WatchError

from empire.features.themes.history_model import (
    BEIJING,
    HistoryError,
    apply_delta,
    delta,
    digest,
    directory,
    dumps,
    expiry,
    instant,
)

READ_STATE = """
return {redis.call('GET', KEYS[1]), redis.call('GET', KEYS[2]),
        redis.call('GET', KEYS[3]), redis.call('HGET', KEYS[4], ARGV[1]),
        redis.call('HLEN', KEYS[4]), redis.call('ZCARD', KEYS[5])}
"""


class ThemeHistory:
    def __init__(self, redis, prefix, *, max_rows=2000, max_rounds=1024,
                 max_day_bytes=128 * 1024 * 1024):
        if not prefix or any(type(v) is not int or v < 1
                             for v in (max_rows, max_rounds, max_day_bytes)):
            raise ValueError('历史前缀与容量必须明确且为正值')
        self.redis, self.prefix = redis, prefix
        self.max_rows, self.max_rounds, self.max_day_bytes = max_rows, max_rounds, max_day_bytes

    def keys(self, day):
        root = f'{self.prefix}:theme-history'
        daily = f'{root}:day:{day.isoformat()}'
        return (f'{root}:current', f'{daily}:base', f'{daily}:meta',
                f'{daily}:events', f'{daily}:rounds')

    async def _now(self):
        seconds, micros = await self.redis.time()
        return datetime.fromtimestamp(seconds + micros / 1000000, BEIJING)

    @staticmethod
    def _load(raw):
        try:
            return json.loads(raw) if raw is not None else None
        except (ValueError, TypeError) as exc:
            raise HistoryError('历史JSON损坏') from exc

    async def append(self, rows, *, observed_at, round_id):
        """Caller must independently establish complete-source proof before calling."""
        observed = instant(observed_at)
        now = await self._now()
        day = observed.astimezone(BEIJING).date()
        if day != now.date() or observed > now + timedelta(minutes=5):
            raise HistoryError('仅允许当日采样，未来时钟超差拒绝')
        if not isinstance(round_id, str) or not 1 <= len(round_id) <= 128:
            raise HistoryError('轮次身份缺失或过长')
        current_rows = directory(rows, self.max_rows)
        fingerprint = digest(current_rows)
        stamp = observed.isoformat()
        current_key, base_key, meta_key, events_key, rounds_key = self.keys(day)
        for _ in range(5):
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(current_key, base_key, meta_key, events_key, rounds_key)
                    raw_current, base, raw_meta, raw_prior, event_count, index_count = await pipe.eval(
                        READ_STATE, 5, current_key, base_key, meta_key, events_key, rounds_key, round_id)
                    current, meta, prior = map(self._load, (raw_current, raw_meta, raw_prior))
                    if meta is None and (base is not None or event_count or index_count):
                        raise HistoryError('当天元信息丢失，不能覆盖残留历史')
                    if meta and (not current or base is None or event_count != meta['count']
                                 or index_count != meta['count'] or current['round_id'] != meta['last']):
                        raise HistoryError('当天历史或当前目录缺失，不得静默补写')
                    if current and digest(current['rows']) != current['digest']:
                        raise HistoryError('当前目录摘要损坏')
                    if prior is not None:
                        if prior['at'] == stamp and prior['digest'] == fingerprint:
                            return {'replayed': True, 'changed': prior['change'] is not None}
                        raise HistoryError('轮次ID已存在但内容或时刻不同')
                    if current and stamp <= current['at']:
                        raise HistoryError('迟到采样不能倒退当前目录')
                    new_day = meta is None
                    change = None if new_day else delta(current['rows'], current_rows)
                    if change is not None and not any(change.values()):
                        change = None
                    event = {'at': stamp, 'digest': fingerprint,
                             'previous': None if new_day else current['round_id'], 'change': change}
                    event_json = dumps(event)
                    base_json = dumps({'at': stamp, 'round_id': round_id,
                                       'digest': fingerprint, 'rows': current_rows})
                    count = 1 if new_day else meta['count'] + 1
                    size = (len(base_json.encode()) if new_day else meta['bytes'])
                    size += len(event_json.encode()) + len(round_id.encode()) * 2 + 32
                    if count > self.max_rounds or size > self.max_day_bytes:
                        raise HistoryError('当天历史容量已达上限，整轮拒绝且保留已有数据')
                    deadline = expiry(day)
                    pipe.multi()
                    pipe.set(current_key, base_json, exat=deadline)
                    if new_day:
                        pipe.set(base_key, base_json, exat=deadline)
                    pipe.set(meta_key, dumps({'count': count, 'bytes': size, 'last': round_id}), exat=deadline)
                    pipe.hset(events_key, round_id, event_json)
                    pipe.zadd(rounds_key, {round_id: observed.timestamp()})
                    pipe.expireat(events_key, deadline)
                    pipe.expireat(rounds_key, deadline)
                    await pipe.execute()
                    return {'replayed': False, 'changed': new_day or change is not None}
                except WatchError:
                    continue
        raise HistoryError('历史并发更新冲突，未提交本轮')

    async def snapshot(self, day, *, at=None):
        now = await self._now()
        if not now.date() - timedelta(days=6) <= day <= now.date():
            raise HistoryError('查询日期不在最近七个自然日内')
        if at is not None:
            at = instant(at)
            if at.astimezone(BEIJING).date() != day:
                raise HistoryError('回放时刻不属于所选日期')
        _, base_key, meta_key, events_key, rounds_key = self.keys(day)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.get(base_key).get(meta_key).hgetall(events_key).zrange(rounds_key, 0, -1, withscores=True)
            base_raw, meta_raw, event_map, ordered = await pipe.execute()
        if base_raw is None and meta_raw is None and not event_map and not ordered:
            return None
        try:
            base, meta = self._load(base_raw), self._load(meta_raw)
            if (not base or not meta or not 1 <= meta['count'] <= self.max_rounds
                    or meta['count'] != len(event_map) or meta['count'] != len(ordered)
                    or ordered[-1][0] != meta['last'] or ordered[0][0] != base['round_id']):
                raise HistoryError('历史不完整，不能回放')
            rows = directory(list(base['rows'].values()), self.max_rows)
            if rows != base['rows'] or digest(rows) != base['digest']:
                raise HistoryError('每日基准摘要不一致')
            previous, previous_at = None, None
            answer = None
            for index, (round_id, score) in enumerate(ordered):
                event = self._load(event_map[round_id])
                stamp = instant(datetime.fromisoformat(event['at']))
                if (event['previous'] != previous or stamp.timestamp() != score
                        or stamp.astimezone(BEIJING).date() != day
                        or (previous_at is not None and stamp <= previous_at)):
                    raise HistoryError('历史链或时刻损坏')
                if index == 0 and (event['at'] != base['at'] or event['change'] is not None):
                    raise HistoryError('每日基准轮次损坏')
                if event['change'] is not None:
                    rows = apply_delta(rows, event['change'], self.max_rows)
                if digest(rows) != event['digest']:
                    raise HistoryError('历史差异摘要不一致')
                if at is None or stamp <= at:
                    answer = {'at': event['at'], 'round_id': round_id,
                              'rows': [dict(v) for v in rows.values()], 'first_at': base['at']}
                previous, previous_at = round_id, stamp
            return answer
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoryError('历史损坏或不完整，不能回放') from exc
