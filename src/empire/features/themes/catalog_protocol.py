"""Strict decoder for the app's themeListResp protobuf body (channel 3009).

This parses a complete *body*, not a socket stream or a completeness certificate.
No transport or registered collector uses it until anonymous framing is verified.
"""
import math
import re
import struct
from dataclasses import dataclass
from decimal import Decimal


class CatalogError(ValueError):
    """Unrecognized or incomplete source data must not replace a catalog."""


@dataclass(frozen=True)
class Concept:
    theme_id: str
    cid: str
    name: str
    pinyin: str
    ratio: Decimal
    limit_up_count: int

    @property
    def identity(self):
        return self.theme_id, self.cid

    @property
    def hot_score(self):
        return None

    @property
    def rank_no(self):
        return None


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    description: str
    pinyin: str
    hot_flag: int
    hot_score: int
    limit_up_count: int
    up_count: int
    new_flag: int
    plate_switch: str
    created_at: str
    ratio: Decimal
    display_order: int
    rank_no: int | None
    concepts: tuple[Concept, ...]


@dataclass(frozen=True)
class Catalog:
    code_switch: int
    state: int
    themes: tuple[Theme, ...]


def _varint(body, offset):
    value = 0
    for number in range(10):
        if offset >= len(body):
            raise CatalogError('protobuf变长整数截断')
        byte = body[offset]
        offset += 1
        if number == 9 and byte > 1:
            raise CatalogError('protobuf变长整数溢出')
        value |= (byte & 127) << (number * 7)
        if byte < 128:
            return value, offset
    raise CatalogError('protobuf变长整数超长')


def _fields(body, schema, repeated=()):
    result, offset = {}, 0
    while offset < len(body):
        tag, offset = _varint(body, offset)
        field, wire = tag >> 3, tag & 7
        if field not in schema or schema[field] != wire:
            raise CatalogError('目录字段或wire类型不符合已核实协议')
        if field in result and field not in repeated:
            raise CatalogError('目录标量字段重复，拒绝静默覆盖')
        if wire == 0:
            value, offset = _varint(body, offset)
            if value > 0xFFFFFFFF:
                raise CatalogError('目录uint32溢出')
        else:
            if wire == 2:
                size, offset = _varint(body, offset)
            else:
                size = 4
            end = offset + size
            if end > len(body):
                raise CatalogError('目录protobuf字段截断')
            value, offset = body[offset:end], end
        if field in repeated:
            result.setdefault(field, []).append(value)
        else:
            result[field] = value
    return result


def _text(fields, key, limit=128, *, identity=False):
    try:
        value = fields.get(key, b'').decode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise CatalogError('目录文本不是有效UTF-8') from exc
    if len(value) > limit or '\x00' in value:
        raise CatalogError('目录文本超限或包含NUL')
    if identity and not re.fullmatch(r'[0-9]{1,32}', value):
        raise CatalogError('目录来源ID缺失或无效')
    return value


def _name(fields):
    value = _text(fields, 2)
    if not value.strip() or '***' in value:
        raise CatalogError('目录名称缺失或被掩码')
    return value


def _ratio(fields, key):
    value = struct.unpack('<f', fields.get(key, b'\x00' * 4))[0]
    if not math.isfinite(value):
        raise CatalogError('目录涨跌幅非有限数')
    # The wire is binary32. Preserve its exact value, with no guessed decimal scale.
    # Display rounding and SQL precision require a separately verified mapping.
    return Decimal.from_float(value)


def decode_catalog(body, *, max_bytes=1024 * 1024, max_themes=2000, max_concepts=10000):
    """Preserve source order and parent-scoped CID; fail closed on schema changes.

    The response has no total-count field. Caller must verify transport framing
    and snapshot/state semantics before declaring this a complete source catalog.
    """
    if any(type(v) is not int or v <= 0 for v in (max_bytes, max_themes, max_concepts)):
        raise ValueError('目录容量必须为正整数')
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise CatalogError('目录正文为空、类型错误或超限')
    fields = _fields(body, {1: 0, 2: 0, 10: 2}, (10,))
    items = fields.get(10, [])
    if not 1 <= len(items) <= max_themes:
        raise CatalogError('目录题材为空或超限')
    themes, ids, rank, concept_count = [], set(), 0, 0
    for order, raw in enumerate(items):
        item = _fields(raw, {1: 2, 2: 2, 3: 2, 4: 2, 5: 0, 6: 0, 7: 0,
                             8: 0, 9: 0, 10: 2, 11: 2, 12: 5, 13: 2}, (13,))
        theme_id = _text(item, 1, 32, identity=True)
        if theme_id in ids:
            raise CatalogError('主题材ID重复，不能以去重掩盖遗漏')
        ids.add(theme_id)
        children, cids = [], set()
        for raw_child in item.get(13, []):
            concept_count += 1
            if concept_count > max_concepts:
                raise CatalogError('子题材数量超限')
            child = _fields(raw_child, {1: 2, 2: 2, 3: 2, 4: 5, 5: 0})
            cid = _text(child, 1, 32, identity=True)
            if cid in cids:
                raise CatalogError('同一主题材内CID重复')
            cids.add(cid)
            children.append(Concept(theme_id, cid, _name(child), _text(child, 3),
                                    _ratio(child, 4), child.get(5, 0)))
        is_new = item.get(9, 0)
        if not is_new:
            rank += 1
        themes.append(Theme(theme_id, _name(item), _text(item, 3, 8192),
                            _text(item, 4), item.get(5, 0), item.get(6, 0),
                            item.get(7, 0), item.get(8, 0), is_new,
                            _text(item, 10, 32), _text(item, 11, 32), _ratio(item, 12),
                            order, None if is_new else rank, tuple(children)))
    return Catalog(fields.get(1, 0), fields.get(2, 0), tuple(themes))
