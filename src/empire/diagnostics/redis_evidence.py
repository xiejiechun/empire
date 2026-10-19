"""Read-only bounded projections of existing temporary records, never new keys."""
import json

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from empire.diagnostics.readonly import DiagnosticLimit
from empire.plugins.collection.records import LIST_ERROR_SUMMARIES, RecordsPlugin

CONTROL = """
if redis.call('STRLEN', KEYS[1]) > 8388608 then
    return cjson.encode({truncated=true, reason='control exceeds 8 MiB'})
end
local raw = redis.call('GET', KEYS[1])
if not raw then return false end
if #raw > 8388608 then return cjson.encode({truncated=true, reason='control exceeds 8 MiB'}) end
local value = cjson.decode(raw)
local job = (value.jobs or {})[ARGV[1]]
local history = {}
for _, row in ipairs(value.history or {}) do
    if row.task_id == ARGV[1] then
        table.insert(history, row)
        if #history == 3 then break end
    end
end
local result = cjson.encode({job=job or cjson.null, history=history})
if #result > 131072 then return cjson.encode({truncated=true, reason='project state exceeds 128 KiB'}) end
return result
"""

CHECKPOINT = """
if redis.call('HSTRLEN', KEYS[1], 'cursor') > 131072 then
    return cjson.encode({truncated=true, reason='cursor exceeds 128 KiB'})
end
local fields = redis.call('HMGET', KEYS[1], 'revision', 'cursor')
local revision, cursor = fields[1], fields[2]
return cjson.encode({revision=revision or cjson.null, cursor=cursor or cjson.null})
"""

QUEUE = """
local total = redis.call('XLEN', KEYS[1])
local jobs = cjson.decode(ARGV[1])
local accepted = {}
for _, job in ipairs(jobs) do accepted[job] = true end
local found, seen, bytes, unreadable, ids, next_id = 0, 0, 0, 0, {}, '-'
for slot=1,5 do
    if seen == total or bytes >= 262144 then break end
    local rows = redis.call('XRANGE', KEYS[1], next_id, '+', 'COUNT', 1)
    if #rows == 0 then break end
    local row = rows[1]
    next_id = '(' .. row[1]
    local raw = nil
    for i=1,#row[2],2 do if row[2][i] == 'envelope' then raw = row[2][i+1] end end
    if not raw then unreadable = unreadable + 1
    else
        bytes = bytes + #raw
        local ok, envelope = false, nil
        if #raw <= 262144 then ok, envelope = pcall(cjson.decode, raw) end
        if not ok or type(envelope) ~= 'table' then unreadable = unreadable + 1
        elseif accepted[envelope.job_key] then found = found + 1; table.insert(ids, row[1]) end
    end
    seen = seen + 1
end
local complete = seen == total and unreadable == 0
return cjson.encode({stream_total=total, project_lower_bound=found, scanned=seen,
    fetched_envelope_bytes=bytes, unreadable=unreadable, stream_ids=ids,
    exact=complete, truncated=not complete})
"""

ERROR_DETAIL = """
local total = redis.call('LLEN', KEYS[1])
local rows = redis.call('LRANGE', KEYS[1], 0, 299)
for _, raw in ipairs(rows) do
    if #raw <= 262144 then
        local ok, row = pcall(cjson.decode, raw)
        if ok and row.id == ARGV[1] then return raw end
    else return cjson.encode({truncated=true, reason='oversized error record; ID not verifiable'}) end
end
if total > 300 then return cjson.encode({truncated=true, reason='error list exceeds owned retention; ID not disproved'}) end
return false
"""

PROGRESS = """
if redis.call('STRLEN', KEYS[1]) > 131072 then return cjson.encode({truncated=true, reason='progress exceeds 128 KiB'}) end
local value = redis.call('GET', KEYS[1])
return value or false
"""

READ_SCRIPTS = frozenset((CONTROL, CHECKPOINT, QUEUE, ERROR_DETAIL, PROGRESS, LIST_ERROR_SUMMARIES))
COMMAND_COST = {CONTROL: 2, CHECKPOINT: 2, QUEUE: 6, ERROR_DETAIL: 2,
                PROGRESS: 2, LIST_ERROR_SUMMARIES: 3}


class RedisEvidence:
    def __init__(self, client, prefix, budget):
        self.client, self.prefix, self.budget = client, prefix, budget
        self.unavailable = False
        # Reuse the record service's authoritative physical key constructor.
        self.records = RecordsPlugin()
        self.records.redis = self

    async def evaluate(self, script, count, *args):
        if script not in READ_SCRIPTS:
            raise ValueError('诊断拒绝未登记的 Redis 脚本')
        if self.unavailable:
            raise DiagnosticLimit('Redis 已不可用；没有重复连接或重试，其他来源证据继续读取')
        try:
            return await self.budget.redis_call(self.client.eval, script, count, *args,
                                               command_cost=COMMAND_COST[script])
        except (TimeoutError, OSError, RedisConnectionError, RedisTimeoutError):
            self.unavailable = True
            raise

    async def control(self, project):
        raw = await self.evaluate(CONTROL, 1, f'{self.prefix}:collection:control:v1', project)
        return json.loads(raw) if raw else None

    async def checkpoint(self, job):
        raw = await self.evaluate(CHECKPOINT, 1, f'{self.prefix}:checkpoint:{job}')
        value = json.loads(raw)
        if value.get('cursor'):
            value['cursor'] = json.loads(value['cursor'])
        return value

    async def progress(self, job):
        raw = await self.evaluate(PROGRESS, 1, f'{self.prefix}:archive:progress:{job}')
        return json.loads(raw) if raw else None

    async def queue(self, jobs):
        raw = await self.evaluate(QUEUE, 1, f'{self.prefix}:ingest', json.dumps(jobs))
        return json.loads(raw)

    async def errors(self, project):
        result = await self.evaluate(LIST_ERROR_SUMMARIES, 2,
            self.records._key('errors', project), self.records._revision_key('errors', project),
            '', 0, self.budget.limits.errors)
        rows = [json.loads(raw) for raw in result[4:]]
        total = int(result[1])
        return {'revision': str(result[0]), 'total': total, 'rows': rows,
                'truncated': total > len(rows), 'body_included': False}

    async def error(self, project, ident):
        raw = await self.evaluate(ERROR_DETAIL, 1, self.records._key('errors', project), ident)
        return json.loads(raw) if raw else None
