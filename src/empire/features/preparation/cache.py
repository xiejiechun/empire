"""Seven-day, scope/version-bound preparation reports; never stores partial checks."""
import hashlib
import json
from dataclasses import asdict

from empire.features.preparation.catalog import BY_ID, REQUIREMENTS
from empire.features.preparation.research import RESEARCH_VERSION, required_ids

TTL_SECONDS = 7 * 24 * 60 * 60
MAX_BYTES = 8 * 1024 * 1024


def cache_identity(contributions, plugins, context):
    """Bind business checks to their contract, rather than an unrelated release."""
    providers = []
    for contribution in contributions:
        declaration = asdict(contribution)
        for field in ('source_tests', 'archive_tests', 'rule_tests', 'integration_tests', 'page_id'):
            declaration.pop(field, None)
        providers.append([declaration, bool(context.optional(contribution.capability))])
    capabilities = {c.capability for c in contributions}
    storage = [(p.manifest.id, getattr(p, 'namespace', None), getattr(p, 'source', None))
               for p in plugins if capabilities.intersection(p.manifest.provides)]
    mysql = context.optional('mysql.store')
    settings = getattr(mysql, 'settings', {}) if mysql else {}
    database = {name: settings.get(name) for name in ('host', 'port', 'database')}
    return [3, RESEARCH_VERSION, [asdict(r) for r in REQUIREMENTS], providers, storage, database]


class PreparationCache:
    def __init__(self, store, identity, scope):
        self.store = store
        self.scope = scope.label()
        self.total = len(required_ids(scope)) if scope.scan == 'research' else len(REQUIREMENTS)
        digest = hashlib.sha256(json.dumps([identity, asdict(scope)], sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
        self.key = f'{store.prefix}:preparation:report:{digest}'

    async def read(self):
        raw = await self.store.client.get(self.key)
        if not raw or len(raw.encode() if isinstance(raw, str) else raw) > MAX_BYTES:
            return None
        try:
            report = json.loads(raw)
            if (report['checking'] is not False or report['scope'] != self.scope
                    or report['checked_requirements'] != self.total
                    or report['total_requirements'] != self.total
                    or [row['id'] for row in report['rows']] != [r.id for r in REQUIREMENTS]):
                return None
            # Compare the whole schema, including nested values, against its checksum.
            checksum = report.pop('cache_sha256')
            if checksum != self.checksum(report):
                return None
            for row in report['rows']:
                row['specification'] = BY_ID[row['id']]
                for checks in [row['checks'], *[p['checks'] for p in row['providers']]]:
                    for item in checks:
                        if 'findings' in item:
                            item['findings'] = tuple(item['findings'])
            report['cache_note'] = '已读取 Redis 检查结果（保存 7 天）；需要最新结果请点击重新检查。'
            return report
        except (ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def checksum(report):
        return hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    async def write(self, report):
        payload = {**report, 'rows': [{k: v for k, v in row.items() if k != 'specification'}
                                     for row in report['rows']]}
        payload['cache_sha256'] = self.checksum(payload)
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode()) > MAX_BYTES:
            raise ValueError('检查结果超过缓存大小上限')
        await self.store.client.set(self.key, raw, ex=TTL_SECONDS)
