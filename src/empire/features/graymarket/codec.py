"""Bounded transport representation; SQL facts remain typed columns."""

import base64
import json
import zlib

from empire.features.graymarket.contract import MAX_DAY_BYTES, validate


def pack(rows):
    validate(rows)
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    body = base64.b64encode(zlib.compress(raw)).decode()
    if len(body) > 480000:
        raise ValueError("资金榜压缩消息超过480000字节，拒绝截断")
    return dict(codec="zlib-json-v1", size=len(raw), body=body)


def unpack(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"codec", "size", "body"}
        or value["codec"] != "zlib-json-v1"
        or type(value["size"]) is not int
        or not 1 <= value["size"] <= MAX_DAY_BYTES
        or not isinstance(value["body"], str)
        or len(value["body"]) > 480000
    ):
        raise ValueError("资金榜压缩消息边界无效")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(base64.b64decode(value["body"], validate=True), value["size"] + 1)
        if (
            len(raw) != value["size"]
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ValueError("资金榜压缩消息不完整")
        return validate(json.loads(raw))
    except (ValueError, zlib.error) as exc:
        raise ValueError("资金榜压缩消息损坏") from exc
