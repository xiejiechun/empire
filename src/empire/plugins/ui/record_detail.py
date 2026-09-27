import json
from datetime import datetime

from empire.core.redaction import Redactor
from empire.core.time import CHINA

ARCHIVE_STATUS = {"complete": "已完成", "replayed": "已确认重放", "superseded": "已被新批次替代",
                  "invalid": "校验失败", "failed": "归档失败"}


def record_time(value):
    if not value:
        return "—"
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, CHINA).strftime("%m-%d %H:%M:%S")
    try:
        return datetime.fromisoformat(value).astimezone(CHINA).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def record_detail(record, kind, config):
    record = Redactor.from_config(config).value(record)
    lines = [f"记录：{record['id']}    项目：{record.get('project_id', '—')}",
             f"时间：{record_time(record.get('created_at'))}    应用版本：{record.get('version', '—')}"]
    if kind == "errors":
        original_bytes = record.get("original_bytes")
        length = f"{original_bytes} 字节" if original_bytes is not None else "未知（未完整读取）"
        lines.extend([f"阶段：{record.get('stage', '—')}    HTTP 状态：{record.get('status_code') or '—'}",
                      f"请求地址：{record.get('request_url') or '—'}", f"错误：{record.get('error', '')}",
                      "元数据：" + json.dumps(record.get("metadata", {}), ensure_ascii=False, indent=2),
                      f"原文长度：{length}    样本截断：{'是' if record.get('body_truncated') else '否'}",
                      f"已读正文：{record.get('observed_bytes', original_bytes) or 0} 字节",
                      f"原文 SHA-256：{record.get('original_sha256') or '未知（未完整读取）'}",
                      f"脱敏样本 SHA-256：{record.get('sample_sha256') or '—'}",
                      "", "错误原文样本（已脱敏，最多 64 KiB）：", record.get("body") or "无原文样本"])
    else:
        processed = record.get("processed_count")
        written = record.get("written_count")
        no_write = (processed - written if type(processed) is int and type(written) is int
                    and 0 <= written <= processed else "—")
        lines.extend([f"状态：{ARCHIVE_STATUS.get(record.get('status'), record.get('status', '—'))}",
                      f"开始：{record_time(record.get('started_at'))}    结束：{record_time(record.get('finished_at'))}（北京时间）",
                      f"已处理记录：{processed if processed is not None else '—'}    "
                      f"业务写入记录：{written if written is not None else '—'}",
                      f"确认无需写入：{no_write}",
                      f"数据批次：{record.get('snapshot_id', '—')}",
                      "失败原因：" + (record.get("error") or "无")])
    return "\n".join(lines)
