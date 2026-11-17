"""Atomic bounded volatile snapshot admission shared by source-owned stores."""

SAVE = """
for i,expected in ipairs({'zset','hash'}) do
  local kind = redis.call('TYPE', KEYS[i+1]).ok
  if kind ~= 'none' and kind ~= expected then return redis.error_reply('snapshot key type mismatch') end
end
local version = tonumber(ARGV[1])
local prior = tonumber(redis.call('HGET', KEYS[3], 'checked') or '0')
if version <= prior then return {-1,0} end
-- Empty body requests confirmation only. Never mutate before determining
-- whether the existing indexed, unexpired body can prove equality.
if ARGV[3] == '' then
  local latest = redis.call('HGET', KEYS[3], 'latest') or ''
  local score = tonumber(redis.call('ZSCORE', KEYS[2], latest) or '')
  if redis.call('HGET', KEYS[3], 'digest') ~= ARGV[2] or not score
     or score <= tonumber(ARGV[5]) or redis.call('EXISTS', KEYS[1] .. ':' .. latest) == 0 then
    return {-2,0}
  end
end
local size = tonumber(redis.call('HGET', KEYS[3], 'bytes') or '0')
if not size or size < 0 then return redis.error_reply('invalid snapshot byte budget') end
-- Maintenance can outlive the time index during a long closure. Expired body
-- ledgers must not consume the next trading day's budget. A missing index with
-- still-live bodies is corruption, not permission to forget their memory.
if redis.call('ZCARD', KEYS[2]) == 0 then
  local obsolete = {}
  for _,field in ipairs(redis.call('HKEYS', KEYS[3])) do
    if string.sub(field,1,5) == 'size:' then
      local id = string.sub(field,6)
      if redis.call('EXISTS', KEYS[1] .. ':' .. id) == 1 then
        return redis.error_reply('snapshot index missing for live body')
      end
      table.insert(obsolete, field)
    end
  end
  for _,field in ipairs(obsolete) do redis.call('HDEL', KEYS[3], field) end
  size = 0
end
local removed = 0
local function remove(id)
  size = size - tonumber(redis.call('HGET', KEYS[3], 'size:' .. id) or '0')
  redis.call('DEL', KEYS[1] .. ':' .. id)
  redis.call('HDEL', KEYS[3], 'size:' .. id)
  redis.call('ZREM', KEYS[2], id)
  removed = removed + 1
end
for _,id in ipairs(redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', ARGV[5])) do remove(id) end
local changed = 0
local latest = redis.call('HGET', KEYS[3], 'latest') or ''
if redis.call('HGET', KEYS[3], 'digest') ~= ARGV[2] or redis.call('ZCARD', KEYS[2]) == 0
   or redis.call('EXISTS', KEYS[1] .. ':' .. latest) == 0 then
  local bodykey = KEYS[1] .. ':' .. ARGV[1]
  redis.call('SET', bodykey, ARGV[3])
  redis.call('PEXPIREAT', bodykey, math.floor(tonumber(ARGV[8])/1000) + tonumber(ARGV[4])*1000)
  redis.call('HSET', KEYS[3], 'size:' .. ARGV[1], string.len(ARGV[3]))
  redis.call('ZADD', KEYS[2], ARGV[8], ARGV[1])
  size = size + string.len(ARGV[3])
  changed = 1
  redis.call('HSET', KEYS[3], 'latest', ARGV[1])
end
while size > tonumber(ARGV[6]) or redis.call('ZCARD', KEYS[2]) > tonumber(ARGV[7]) do
  local first = redis.call('ZRANGE', KEYS[2], 0, 0)[1]
  if not first then break end
  remove(first)
end
redis.call('HSET', KEYS[3], 'checked', ARGV[1], 'digest', ARGV[2], 'bytes', size)
redis.call('HINCRBY', KEYS[3], 'evicted', removed)
redis.call('EXPIRE', KEYS[2], ARGV[4])
redis.call('EXPIRE', KEYS[3], ARGV[4])
return {changed,removed}
"""
