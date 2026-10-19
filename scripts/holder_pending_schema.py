"""Explicit, locked holder envelope conversion; never called at app startup."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import Envelope, make_envelope
from empire.core.config import load_config
from empire.features.holders.dataset import HolderDataset
from empire.plugins.infra.redis_store import create_client

REPLACE = """
local row = redis.call('XRANGE', KEYS[1], ARGV[1], ARGV[1])
if #row ~= 1 then return redis.error_reply('Pending message changed or missing') end
local fields = row[1][2]
if #fields ~= 2 or fields[1] ~= 'envelope' or fields[2] ~= ARGV[2] then
    return redis.error_reply('Pending envelope changed')
end
local id = redis.call('XADD', KEYS[1], '*', 'envelope', ARGV[3])
redis.call('XDEL', KEYS[1], ARGV[1])
return id
"""


def convert(raw):
    old = Envelope.model_validate_json(raw)
    if old.source != 'ths' or old.dataset != 'holders.reports' or old.job_key != 'ths-holders-v1':
        raise ValueError('消息不属于持有人项目')
    if old.schema_version != 4 or set(old.raw_payload) != {'page', 'unit', 'reports', 'manifest'}:
        raise ValueError('不是明确支持的持有人schema4消息')
    original = make_envelope(source=old.source, dataset=old.dataset, schema_version=4,
        business_key=old.business_key, job_key=old.job_key, run_id=old.run_id,
        batch_id=old.batch_id, payload=old.raw_payload)
    if (old.event_id, old.content_hash) != (original.event_id, original.content_hash):
        raise ValueError('待转换消息身份或内容摘要不符')
    new = make_envelope(source=old.source, dataset=old.dataset, schema_version=5,
        business_key=old.business_key, job_key=old.job_key, run_id=old.run_id,
        batch_id=old.batch_id, payload={**old.raw_payload, 'gaps': []})
    new = new.model_copy(update={key: getattr(old, key) for key in (
        'observed_at', 'source_event_time', 'available_at', 'availability_basis',
        'source_url', 'source_record_id')})
    HolderDataset().normalize(new)
    return new


async def run_pending(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    client = create_client(cfg['redis'])
    stream = cfg['redis']['namespace'] + ':ingest'
    result = dict(checked_at=datetime.now(UTC).isoformat(), applied=args.apply,
                  scanned=0, converted=[], current_schema=0, other_datasets=0)
    try:
        # Freeze the upper stream ID; replacement IDs must not be scanned again.
        last = await client.xrevrange(stream, count=1)
        end = last[0][0] if last else '0-0'
        position = '-'
        while True:
            rows = await client.xrange(stream, min=position, max=end, count=20)
            if not rows:
                break
            for ident, fields in rows:
                result['scanned'] += 1
                if result['scanned'] > 15001:
                    raise ValueError('显式维护扫描超过15001消息边界')
                raw = fields.get('envelope', '')
                old = Envelope.model_validate_json(raw)
                if old.dataset != 'holders.reports':
                    result['other_datasets'] += 1
                    continue
                if old.schema_version == 5:
                    HolderDataset().normalize(old)
                    result['current_schema'] += 1
                    continue
                new = convert(raw)
                row = dict(old_stream_id=ident, old_event_id=old.event_id,
                           old_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                           new_event_id=new.event_id, batch_id=new.batch_id,
                           page=new.raw_payload['page'], unit=new.raw_payload['unit'])
                if args.apply:
                    row['new_stream_id'] = await client.eval(REPLACE, 1, stream, ident, raw, new.model_dump_json())
                result['converted'].append(row)
            position = '(' + rows[-1][0]
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf8')
        result['pending_after'] = await client.xlen(stream)
        result['business_payload_preserved'] = True
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf8')
        print('PASS explicit holder pending', 'conversion' if args.apply else 'preflight',
              len(result['converted']), 'messages')
    finally:
        await client.aclose()
        if lock:
            lock.unlock()
