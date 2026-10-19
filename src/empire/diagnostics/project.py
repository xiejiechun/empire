"""Bounded, per-project evidence, without starting a collector or archive worker."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from datetime import date, datetime

from sqlalchemy import text

from empire.core.redaction import Redactor, clip_text
from empire.core.time import CHINA
from empire.diagnostics.declarations import project_declaration, query_preview
from empire.diagnostics.readonly import Budget, DiagnosticLimit, Limits, ReadOnlyMySQL
from empire.diagnostics.redis_evidence import RedisEvidence
from empire.plugins.infra.redis_store import create_client


def stamp():
    return datetime.now(CHINA).isoformat()


def isolation(snapshot, project):
    if snapshot is None:
        return {'status': 'unknown', 'reason': '隔离集合仅在运行中归档器内存；CLI 无进程间快照，历史错误不能证明当前隔离'}
    plugin = next((p for p in snapshot.get('plugins', []) if p.get('id') == 'pipeline.archive'), None)
    if not plugin or plugin.get('state') not in ('RUNNING', 'DEGRADED'):
        return {'status': 'unknown', 'reason': '传入运行快照中归档器未运行或不可用'}
    health = plugin.get('health', {})
    if 'blocked_projects' not in health or 'blocked' not in health:
        return {'status': 'unknown', 'reason': '运行快照缺少隔离字段'}
    return {'status': 'ok', 'global_blocked': bool(health['blocked']),
            'project_blocked': project in health['blocked_projects'],
            'source': '调用方传入的现有 Runtime.snapshot；非跨服务原子快照'}


def sql_state(mysql, namespace, project):
    # Read only a bounded projection of the existing authority, not every unit
    # or historical body stored in collection_state.
    with mysql.read_engine.connect() as conn:
        row = conn.execute(text("""SELECT source,dataset,updated_at,
            OCTET_LENGTH(payload) AS state_bytes,
            CASE WHEN OCTET_LENGTH(JSON_EXTRACT(payload,'$.progress'))<=131072
              THEN JSON_EXTRACT(payload,'$.progress') END AS progress,
            CASE WHEN OCTET_LENGTH(JSON_EXTRACT(payload,'$.progress'))>131072
              THEN 1 ELSE 0 END AS progress_truncated,
            CASE WHEN OCTET_LENGTH(JSON_EXTRACT(payload,'$.coverage'))<=131072
              THEN JSON_EXTRACT(payload,'$.coverage') END AS coverage,
            CASE WHEN OCTET_LENGTH(JSON_EXTRACT(payload,'$.coverage'))>131072
              THEN 1 ELSE 0 END AS coverage_truncated,
            JSON_EXTRACT(payload,'$.contract_version') AS contract_version
            FROM collection_state WHERE namespace=:namespace AND project_id=:project LIMIT 1"""),
            {'namespace': namespace, 'project': project}).mappings().first()
        if row is None:
            return None
        result = dict(row)
        result['truncated'] = bool(result['progress_truncated'] or result['coverage_truncated'])
        result['projection_only'] = True
        return result


def sql_policy(mysql, namespace, project):
    with mysql.read_engine.connect() as conn:
        row = conn.execute(text("""SELECT updated_at,OCTET_LENGTH(payload) AS bytes,
            CASE WHEN OCTET_LENGTH(payload)<=16384 THEN payload END AS policy
            FROM app_setting WHERE namespace=:namespace AND kind='task'
            AND setting_key=:project LIMIT 1"""),
            {'namespace': namespace, 'project': project}).mappings().first()
        if not row:
            return None
        result = dict(row)
        result['truncated'] = result['bytes'] > 16384
        return result


def _safe_section(data, redactor, maximum, text_limit=65536):
    # Redaction precedes JSON serialization; trim actual UTF-8 bytes afterwards.
    safe = redactor.value(data, max_depth=16, max_items=100, max_nodes=6000,
                          max_bytes=maximum, text_limit=text_limit)
    encoded = json.dumps(safe, ensure_ascii=False, default=str)
    if len(encoded.encode()) > maximum:
        return {'excerpt': clip_text(encoded, max(1, maximum - 200)), 'truncated': True}
    if '[size limited]' in encoded or '[depth limited]' in encoded:
        return {'value': safe, 'truncated': True}
    return safe


async def diagnose_project(cfg, project, *, error_id=None, security='', day='', limits=None,
                           manager=None, client=None, mysql=None, runtime_snapshot=None):
    """Read one registered project; injected dependencies support isolated tests.

    runtime_snapshot may be an existing Runtime.snapshot() result. This function
    never constructs or starts Runtime and never persists a second state path.
    """
    if error_id is not None and (not isinstance(error_id, str) or not error_id
                                 or len(error_id.encode()) > 256):
        raise ValueError('错误记录必须使用不超过 256 字节的确切 ID')
    if security and not re.fullmatch(r'[0-9]{6}\.(?:SH|SZ|BJ)', security):
        raise ValueError('--security 须为统一证券身份，例如 000001.SZ')
    if day and date.fromisoformat(day).isoformat() != day:
        raise ValueError('--date 须为 YYYY-MM-DD')
    budget = Budget(limits or Limits())
    redactor = Redactor.from_config(cfg)
    declaration, queries = project_declaration(cfg, project, manager)
    report = {'schema': 1, 'project_id': project, 'started_at': stamp(), 'read_only': True,
              'status': 'ok', 'sections': {},
              'note': '各项分时读取，非 Redis/SQL 原子快照。任务阶段与 next_due 来自临时记录；'
                      '正式预览不证明来源完整、时效或全部待归档为零。',
              'limits_note': '队列最多逐条读取 5 个现有 Envelope；累计达到 256 KiB 后不取下一条，'
                             '最后一条可超过此阈值，超过 256 KiB 的正文不解析。错误详情最多查现有保留的 300 条；'
                             '控制状态读取上限 8 MiB，断点/归档进度各 128 KiB。报告上限不等同 Redis 服务总内存上限。'}

    def put(name, value, *, status='ok', reason='', began=None):
        maximum = min(196608, budget.limits.report_bytes // 3)
        safe = _safe_section(value, redactor, maximum, budget.limits.body_bytes)
        if isinstance(value, dict) and value.get('truncated'):
            status = 'partial'
        if isinstance(safe, dict) and safe.get('truncated'):
            status = 'partial'
        report['sections'][name] = {'status': status, 'started_at': began or stamp(),
            'acquired_at': stamp(), 'reason': redactor.text(reason, 2048), 'data': safe}

    async def capture(name, operation):
        began = stamp()
        try:
            budget.timeout()
            value = await asyncio.wait_for(operation(), budget.remaining())
            put(name, value, status='unknown' if value is None else 'ok', began=began,
                reason='当前存储没有该项证据' if value is None else '')
        except (DiagnosticLimit, TimeoutError) as exc:
            put(name, None, status='partial', began=began,
                reason=str(exc) or '读取超时，保留其他已经取得的证据')
        except Exception as exc:
            put(name, None, status='error', began=began,
                reason=f'{type(exc).__name__}: {exc}')

    put('declaration', declaration)
    live = isolation(runtime_snapshot, project)
    put('isolation', live, status=live['status'], reason=live.get('reason', ''))
    own_client, own_mysql = client is None, mysql is None
    namespace = cfg['redis'].get('namespace', 'empire:dev')
    try:
        # Construct connections lazily; connection errors belong to the relevant
        # sections and cannot prevent the other service's evidence from appearing.
        client = client if client is not None else create_client(cfg['redis'])
        redis = RedisEvidence(client, namespace, budget)
        await capture('errors', lambda: redis.errors(project))
        await capture('task_state', lambda: redis.control(project))
        for job in declaration['job_keys']:
            await capture('checkpoint:' + job, lambda job=job: redis.checkpoint(job))
            await capture('archive_progress:' + job, lambda job=job: redis.progress(job))
        await capture('queue', lambda: redis.queue(declaration['job_keys']))
        if error_id is not None:
            async def detail():
                value = await redis.error(project, error_id)
                if value is not None:
                    body = redactor.text(value.get('body', ''))
                    value['body'] = clip_text(body, budget.limits.body_bytes)
                    if len(body.encode()) > budget.limits.body_bytes:
                        value.update(body_truncated=True, truncated=True)
                return value
            await capture('error_detail', detail)
    except asyncio.CancelledError:
        if own_client and client is not None:
            await asyncio.wait_for(client.aclose(), max(.001, min(.2, budget.remaining())))
        raise
    except Exception as exc:
        put('redis_connection', None, status='error', reason=str(exc))
    try:
        mysql = mysql if mysql is not None else ReadOnlyMySQL(cfg['mysql'], budget)
        if isinstance(mysql, ReadOnlyMySQL):
            mysql.budget = budget
        # Injected readers use the same report budget when their implementation
        # accepts it; production counting is enforced per SQL statement.
        await capture('sql_state', lambda: mysql.read(sql_state, mysql, namespace, project))
        await capture('saved_policy', lambda: mysql.read(sql_policy, mysql, namespace, project))
        for capability, plugin in queries.items():
            async def preview(plugin=plugin, capability=capability):
                method, kwargs = query_preview(plugin, security, day)
                plugin = copy.copy(plugin)
                plugin.mysql = mysql
                value = await getattr(plugin, method)(**kwargs)
                return {'capability': capability, 'method': method, 'arguments': kwargs,
                        'result': value, 'scope': '正式有界预览，非完整性验收'}
            await capture('query:' + capability, preview)
        if not queries:
            put('formal_query', None, status='unknown', reason='没有关联的正式查询贡献')
    except Exception as exc:
        put('sql_connection', None, status='error', reason=str(exc))
    finally:
        if own_mysql and mysql is not None:
            mysql.close()
            report['sql_cleanup'] = mysql.cleanup_status()
        if own_client and client is not None:
            try:
                # Socket close is local cleanup; do not wait past the report's deadline.
                await asyncio.wait_for(client.aclose(), max(.001, min(.2, budget.remaining())))
            except (Exception, asyncio.CancelledError):
                pass
    report.update(finished_at=stamp(), budget=budget.report())
    if any(s['status'] != 'ok' for s in report['sections'].values()):
        report['status'] = 'partial'
    if not report.get('sql_cleanup', {'complete': True})['complete']:
        report['status'] = 'partial'
    # Enforce serialized report size as well as per-section bounds.
    render_report(report, budget.limits.report_bytes)
    return report


def render_report(report, maximum=1048576):
    def encode():
        return json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n'
    content = encode()
    if len(content.encode()) <= maximum:
        return content
    report.update(status='partial', truncated=True)
    # Keep every section's status and time while dropping the largest bodies first.
    for _, section in sorted(report.get('sections', {}).items(),
            key=lambda item: len(json.dumps(item[1].get('data'), default=str)), reverse=True):
        section.update(data=None, status='partial', reason='报告达到字节上限，此项正文未输出')
        content = encode()
        if len(content.encode()) <= maximum:
            return content
    raise ValueError('报告字节上限不足以容纳项目诊断状态')
