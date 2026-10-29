"""Explicit maintenance audit continuation; collector cursors remain in Redis."""
import json
from pathlib import Path

from empire.contracts.data import Envelope
from empire.sources.yuanhang_payload import CONTRACT, digest


def load_resume(path, *, inputs):
    if not path:
        return None
    path = Path(path)
    if path.stat().st_size > 128 * 1024**2:
        raise ValueError('初始化审计文件超过128MiB上限')
    report = json.loads(path.read_text('utf-8'))
    if (report.get('bindings') != inputs or report.get('input_identity_verified') is not True
            or report.get('audit_contract') != CONTRACT or not report.get('audit_sources')):
        raise ValueError('初始化审计证据缺失或源码身份改变，须重新完整核实')
    return report


def seed(report, *, target, codes, through):
    if report is None:
        return {}
    if (report.get('target') != target or report.get('stocks') != codes
            or report.get('scope_hash') != digest(codes) or report.get('through') != through):
        raise ValueError('初始化审计的目标库、股票池或截止日不一致')
    result = {}
    for project, saved in report['audit_sources'].items():
        checkpoint = saved['checkpoint']
        cursor = checkpoint['cursor']
        n = cursor['next_index']
        if (type(n) is not int or not 0 <= n <= len(codes) or cursor['scope_hash'] != digest(codes)
                or cursor['through'] != through or set(saved['proofs']) != set(codes[:n])):
            raise ValueError('初始化来源摘要与已入队证券前缀不一致')
        proofs = saved['proofs']
        if project == 'ths-yuanhang-prices':
            proofs = {code: p if 'deferred' in p else {int(y): v for y, v in p.items()}
                      for code, p in proofs.items()}
        elif project != 'ths-yuanhang-financial':
            raise ValueError('初始化审计含未知项目')
        result[project] = dict(checkpoint=checkpoint, proofs=proofs, allowed_codes=codes[:min(n+1,len(codes))])
    return result


async def require_owned_pending(redis, saved):
    """Resume only this report's batches; never drain unrelated business."""
    allowed = {project + '-v1': data['checkpoint']['cursor']['batch_id'] for project, data in saved.items()}
    after = '-'
    while True:
        rows = await redis.client.xrange(redis.stream, min=after, count=100)
        if not rows:
            return
        for _, fields in rows:
            e = Envelope.model_validate_json(fields['envelope'])
            datasets = {'ths-yuanhang-prices-v1': 'yuanhang.price.year',
                        'ths-yuanhang-financial-v1': 'yuanhang.financial'}
            if (e.source != 'ths_yuanhang' or allowed.get(e.job_key) != e.batch_id
                    or datasets.get(e.job_key) != e.dataset):
                raise ValueError('初始化恢复存在不属于原来源审计批次的待归档消息')
            project = e.job_key.removesuffix('-v1')
            if e.raw_payload.get('history', {}).get('code') not in saved[project]['allowed_codes']:
                raise ValueError('初始化恢复消息不属于已入队证券前缀及当前未完成证券')
        after = '(' + rows[-1][0]
