"""Temporary, lossless storage measurement; never a business archive path."""
import ctypes
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import zlib
from pathlib import Path
from urllib.parse import unquote_to_bytes
from uuid import uuid4

from empire.features.kaipanla.source_protocol import TREND_TIMES

INTERFACES = {
    'GetStockTrend': ('trend', 5),
    'GetStockBid': ('bid', 4),
    'GetStockVolTur': ('volumeturnover', 4),
    'GetStockFenBi2': ('fb', 8),
    'GetStockBsvolume': ('bsentrust', 5),
    'GetStockDaDanTrend': ('dadanjinge', 2),
    'GetStockPanKou': (None, None),
    'GetStockZJMMMin': ('List', 4),
    'GetStockChouMa_New': ('List', 11),
    'StockTrendInfo': ('trendList', 6),
}
UNCONFIRMED = [
    '大单明细及筛选统计的独立接口/与分笔字段的可还原关系',
    '竞价主力净额等附加统计的完整字段契约',
    '每分钟独立 OHLC',
]


def decode_body(body, *, maximum=64 * 1024 * 1024):
    if body.lstrip().startswith((b'{', b'[')):
        return body
    compressed = unquote_to_bytes(body.decode('ascii').replace('+', ' '))
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(compressed, maximum + 1)
    if len(decoded) > maximum:
        raise ValueError('source_codec_decoded_limit')
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('source_codec_incomplete_or_trailing_data')
    return decoded


def replay_evidence(value):
    rows, book, indexes = (value.get(k) for k in ('trendList', 'trendListFengDan', 'trendListIndex'))
    if (not isinstance(rows, list) or not rows or not isinstance(book, list) or len(rows) != len(book)
            or any(not isinstance(r, list) or len(r) != 6 for r in rows)
            or any(not isinstance(r, list) or len(r) != 13 for r in book)):
        raise ValueError('replay_price_orderbook_shape_or_alignment')
    times = [str(row[0]).zfill(6) for row in rows]
    if (any(not re.fullmatch(r'\d{6}', t) for t in times)
            or any(a > b for a, b in zip(times, times[1:]))
            or any(str(r[0]).zfill(6) != t for r, t in zip(book, times))):
        raise ValueError('replay_time_alignment_or_order')
    if (not isinstance(indexes, list) or len(indexes) != 2
            or len(indexes[0]) != len(indexes[1]) or len(indexes[0]) != 242):
        raise ValueError('replay_minute_index_shape')
    expected = [int(t.replace(':', '')) for t in TREND_TIMES]
    expected.insert(expected.index(1301), 1300)
    if indexes[0] != expected:
        raise ValueError('replay_minute_index_key_set')
    covered = set()
    for pair in indexes[1]:
        a, b = map(int, str(pair).split(','))
        if not 0 <= a <= b < len(rows):
            raise ValueError('replay_index_outside_source_array')
        covered.update(range(a, b + 1))
    # The 15:00 index may include later source updates (e.g. 15:00:58).
    # Use the complete index-to-array relationship, not an invented exact final second.
    if covered != set(range(len(rows))):
        raise ValueError('replay_incomplete_day_or_unindexed_points')
    return {'rows': len(rows), 'orderbook_rows': len(book), 'distinct_time_labels': len(set(times)),
            'first_time': times[0], 'last_time': times[-1], 'source_min_date': value.get('MinDate'),
            'full_response_parameters': {'isAll': 1, 'start': 0, 'stop': 0},
            'ordered_business_array_sha256': hashlib.sha256(
                json.dumps([rows, book], separators=(',', ':')).encode()).hexdigest()}


def validate(body, action, code, day):
    """Count/identity evidence is independent of any deduplication; preserve duplicates."""
    value = json.loads(body)
    if not isinstance(value, dict) or str(value.get('errcode')) != '0':
        raise ValueError('source_error:' + str(value.get('errcode', 'missing'))
                         if isinstance(value, dict) else 'source_structure')
    returned_day = value.get('day', value.get('Day'))
    if returned_day is None and action not in ('StockTrendInfo', 'GetStockZJMMMin', 'GetStockChouMa_New'):
        raise ValueError('missing_source_day')
    if returned_day is not None and str(returned_day).replace('-', '') != day.strftime('%Y%m%d'):
        raise ValueError('wrong_source_day')
    if value.get('code', code) != code:
        raise ValueError('wrong_source_code')
    if action == 'StockTrendInfo':
        if value.get('MinDate') and day < date_from_source(value['MinDate']):
            raise ValueError('replay_outside_source_supported_history')
        return replay_evidence(value)
    field, width = INTERFACES[action]
    if field is None:
        if not isinstance(value.get('real'), dict) or not isinstance(value.get('weituo'), dict):
            raise ValueError('missing_quote_or_orderbook')
        return {'rows': 1, 'populated_bid_levels': sum(
            bool(value['weituo'].get('b' + str(i), [0])[0]) for i in range(1, 11))}
    rows = value.get(field)
    if not isinstance(rows, list) or not rows:
        raise ValueError('missing_or_empty_series')
    if any(not isinstance(row, list) or len(row) != width for row in rows):
        raise ValueError('changed_row_structure')
    if action == 'GetStockChouMa_New':
        if type(value.get('Total')) is not int or value['Total'] != len(rows):
            raise ValueError('chip_source_total_mismatch')
        return {'rows': len(rows), 'source_state': value.get('State')}
    times = [row[0] for row in rows]
    pattern = r'\d{2}:\d{2}:\d{2}' if action == 'GetStockFenBi2' else r'\d{2}:\d{2}'
    if any(not isinstance(t, str) or not re.fullmatch(pattern, t) for t in times):
        raise ValueError('invalid_time_label')
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError('unordered_source_series')
    if action not in ('GetStockBid', 'GetStockFenBi2') and tuple(times) != TREND_TIMES:
        raise ValueError('minute_key_gap_or_duplicate')
    if action in ('GetStockTrend', 'GetStockBid') and all(row[1] == 0 for row in rows):
        raise ValueError('zero_price_placeholder')
    if action == 'GetStockFenBi2':
        if any(type(value.get(k)) is not int or value[k] != len(rows) for k in ('Count', 'total')):
            raise ValueError('partial_or_inconsistent_source_count')
    return {'rows': len(rows), 'distinct_time_labels': len(set(times)),
            'first_time': times[0], 'last_time': times[-1],
            'ordered_business_array_sha256': hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}


def date_from_source(value):
    from datetime import date
    return date.fromisoformat(value)


def allocated_size(path):
    """Measure NTFS allocation rather than calling logical size physical allocation."""
    if os.name != 'nt':
        return getattr(path.stat(), 'st_blocks', 0) * 512
    class Info(ctypes.Structure):
        _fields_ = [('allocation', ctypes.c_longlong), ('eof', ctypes.c_longlong),
                    ('links', ctypes.c_ulong), ('deleted', ctypes.c_ubyte), ('directory', ctypes.c_ubyte)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                 ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = Info()
        if not kernel.GetFileInformationByHandleEx(handle, 1, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.allocation
    finally:
        kernel.CloseHandle(handle)


class Capture:
    def __init__(self, base):
        self.base = Path(base).resolve()
        self.run_id = uuid4().hex
        self.root = self.base / ('run-' + self.run_id)
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / '.owner').write_text(self.run_id, encoding='ascii')
        self.raw = self.root / 'raw'
        self.compressed = self.root / 'gzip'
        self.raw.mkdir()
        self.compressed.mkdir()
        self.incoming = self.root / 'incoming'
        self.incoming.mkdir()

    def open(self, unified_code):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', unified_code):
            raise ValueError('invalid_security_file_identity')
        return Writer(self, unified_code)

    def measure(self):
        def group(folder):
            files = list(folder.iterdir())
            return {'file_count': len(files), 'logical_bytes': sum(p.stat().st_size for p in files),
                    'allocated_bytes': sum(allocated_size(p) for p in files)}
        return {'raw': group(self.raw), 'gzip': group(self.compressed)}

    def cleanup(self):
        # Only this run, with exact ownership and resolved workspace confinement.
        target = self.root.resolve()
        if (target.parent != self.base or target.name != 'run-' + self.run_id
                or self.root.is_symlink() or (target / '.owner').read_text('ascii') != self.run_id):
            raise RuntimeError('temporary_capture_ownership_changed')
        for child in target.rglob('*'):
            if child.is_symlink() or not child.resolve().is_relative_to(target):
                raise RuntimeError('unsafe_temporary_capture_link')
        shutil.rmtree(target)
        return {'deleted': not target.exists(), 'owned_directory': str(target)}


class Writer:
    def __init__(self, capture, code):
        self.path = capture.raw / (code + '.pack')
        self.zip_path = capture.compressed / (code + '.pack.gz')
        self.file = self.path.open('xb')
        self.zip_file = self.zip_path.open('xb')
        self.zip = gzip.GzipFile(filename='', mode='wb', fileobj=self.zip_file, mtime=0, compresslevel=6)

    def write(self, action, body):
        metadata = json.dumps({'action': action}, separators=(',', ':')).encode('ascii')
        # Retain exact bytes, including encoding/order/duplicates: no JSON reserialization.
        for chunk in (struct.pack('<IQ', len(metadata), len(body)), metadata, body):
            self.file.write(chunk)
            self.zip.write(chunk)

    def close(self):
        self.zip.close()
        self.zip_file.close()
        self.file.close()
        return {'raw_bytes': self.path.stat().st_size, 'gzip_bytes': self.zip_path.stat().st_size,
                'raw_allocated_bytes': allocated_size(self.path), 'gzip_allocated_bytes': allocated_size(self.zip_path)}


def atomic_report(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
