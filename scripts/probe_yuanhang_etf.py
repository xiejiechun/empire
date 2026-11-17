"""Bounded ETF protocol research through shared networking; no business writes."""
import argparse
import asyncio
import configparser
import hashlib
import json
import struct
import zlib
from pathlib import Path

from yuanhang_node_profiles import manager_for

from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.core.redaction import redact
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore
from empire.sources import yuanhang_auth
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService
from empire.sources.yuanhang_transport import request
from empire.sources.yuanhang_wire import decode_response, decode_table, snappy_block


def inspect(body, limit, reserve):
    result = dict(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    if len(body) >= 17:
        result['header'] = list(struct.unpack_from('<HiIHiB', body))
    if len(body) > 21 and result['header'][2] in (102, 240) and result['header'][3] == 514:
        size = struct.unpack_from('<I', body, 17)[0]
        if not 4 < size <= limit:
            raise ValueError('Market file expansion exceeds budget')
        reserve(size)
        decoder = zlib.decompressobj()
        plain = decoder.decompress(body[21:], size + 1)
        if len(plain) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Market file compression invalid')
        if result['header'][2] == 102:
            result['plain_bytes'] = len(plain)
            result['plain_prefix'] = repr(plain[:200])
            result['plain_suffix'] = repr(plain[-200:])
            return result
        ini = configparser.ConfigParser(interpolation=None, strict=True)
        ini.read_string(plain[4:].rstrip(b'\0').decode('gbk'))
        result['sections'] = {s: {k: v for k, v in ini[s].items() if not k.startswith('codelist')} for s in ini.sections()}
        return result
    try:
        result['tables'] = decode_response(body, instance=1, request_id=result['header'][2], limit=limit, reserve=reserve)
    except ValueError as exc:
        result['decoder_error'] = str(exc)
        if len(body) >= 21 and b'hx1.' in body[:40]:
            offset = body.index(b'hx1.')
            try:
                result['table_offset'] = offset
                result['tables'] = [decode_table(body[offset:], limit, reserve, text_encodings={55: 'utf8'})]
            except ValueError as nested:
                result['table_error'] = str(nested)
                if body[offset:offset+6] in (b'hx1.2\0', b'hx1.3\0'):
                    plain = body[offset:offset+6] + snappy_block(body[offset+6:], limit, reserve)
                    result['decoded_header'] = plain[:64].hex()
                    result['decoded_trailer'] = plain[-64:].hex()
                    result['decoded_bytes'] = len(plain)
        if 'tables' not in result:
            result['prefix_hex'] = body[:96].hex()
    return result


async def run(args):
    cfg = load_config()
    manager, identity = manager_for(cfg), None
    counts, report = {}, dict(business_writes=0, registration_requests=0, queries=[])
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    original_passport = yuanhang_auth._passport
    def passport_metadata(item, *positional, **keywords):
        attributes = dict(part.split('=', 1) for part in item.get('passport', '').split('|') if '=' in part)
        report['directory_keys'] = sorted(attributes)
        session = original_passport(item, *positional, **keywords)
        entries = [e.split(':') for e in attributes.get('M_hqdns', '').split(',')]
        report['service_tags'] = [e[2].split(';') if len(e) > 2 else [] for e in entries]
        return session
    yuanhang_auth._passport = passport_metadata
    try:
        await manager.start('infra.http')
        http, pool = manager.registry.get('http.fetch'), manager.registry.get('proxy.pool')
        await pool.snapshot()
        registry = ProfileRegistry(SettingsStore(manager.registry.get('mysql.store'), cfg['redis']['namespace']), WindowsProtection())
        identity = IdentityService(registry, pool, http)
        profiles = await identity.get_profiles()
        nodes = sorted(n for n in identity.online_codes() if n in profiles and profiles[n].provisioned)
        if not nodes:
            raise ValueError('没有在线已就绪远航身份')
        session = await identity.login(nodes[0], project_id='ths-yuanhang-etf-research')
        for query in args.query:
            if len(query) > 4096 or not query.startswith('id=') or 'instance=1' not in query:
                raise ValueError('Research query must be bounded with instance=1')
            result = await request(http, session, query.encode('ascii'), inspect, project_id='ths-yuanhang-etf-research', service=args.service)
            tables = result.pop('tables', [])
            # Only public business metadata, never arbitrary auth/transport content.
            result['tables'] = [dict(fields=t['fields'], count=t['row_count'], extra=t['extra'],
                first=t['rows'][:args.rows], last=t['rows'][-1:]) for t in tables]
            report['queries'].append(dict(query=query, **result))
            print(json.dumps(report['queries'][-1], ensure_ascii=False, default=str), flush=True)
    except Exception as exc:
        report['failure'] = redact(exc, cfg)
        raise
    finally:
        if identity:
            await identity.close()
        await manager.shutdown()
        yuanhang_auth._passport = original_passport
        report['routes'] = counts
        for variable, token in zip((USE_PROXY, PROXY_FALLBACK, ROUTE_COUNTS), tokens, strict=True):
            variable.reset(token)
        with Path(args.output).open('x', encoding='utf8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, default=str)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', action='append', required=True)
    parser.add_argument('--rows', type=int, choices=range(6), default=2)
    parser.add_argument('--output', required=True)
    parser.add_argument('--service')
    options = parser.parse_args()
    if Path(options.output).exists():
        parser.error('Output must not exist')
    asyncio.run(run(options))
