"""One bounded transaction for explicitly independent, disjoint archive units.

Called under the coordinator's project/table/cache ownership. Invalidation of a
whole source is incompatible with this declaration and stays on the single path.
"""
import pickle

from empire.plugins.pipeline.fingerprints import digest


async def archive_units(worker, records):
    catalog, metrics = worker.catalog, worker.metrics
    first = records[0]['envelope']
    project = catalog.project_id(first)
    namespace = records[0]['namespace']
    source = catalog.fingerprint_source(first)
    version_contract = catalog.fingerprint_version(namespace)
    plans, identities = [], set()
    with metrics.span(project, 'plan'):
        for record in records:
            envelope, data = record['envelope'], record['normalized']
            name, plan = record['namespace'], record['plan']
            if (name != namespace or catalog.fingerprint_source(envelope) != source
                    or identities.intersection(plan)
                    or len(records) > 1 and not catalog.mapping(envelope).batch_independent):
                raise ValueError('归档批次含冲突身份或未声明的独立单元')
            identities.update(plan)
            plans.append(plan)
    with metrics.span(project, 'cache_read'):
        cached = await worker.fingerprints.get(namespace, source, list(identities))
    prepared, sql = [], []
    for record, plan in zip(records, plans):
        envelope, data = record['envelope'], record['normalized']
        confirmed, calculated, pending, stale = {}, {}, set(), 0
        with metrics.span(project, 'hash'):
            for ident, (content, version) in plan.items():
                value = calculated[ident] = (record['hashes'][ident] if 'hashes' in record else
                                            {'hash': digest(content), 'version': version})
                old = cached.get(ident)
                if old and version_contract.compare(version, old['version']) < 0:
                    stale += 1
                elif old and old['hash'] == value['hash']:
                    confirmed[ident] = value
                else:
                    pending.add(ident)
        metrics.add(project, checked=len(plan), equal=len(confirmed), stale=stale,
                    missing=len(plan.keys() - cached.keys()), changed=len(pending & cached.keys()))
        count = data.get('row_count', data.get('expected_count', 0))
        outcome = dict(status=catalog.stale_outcome(envelope) if stale else 'complete',
                       row_count=count, written_count=0)
        needs_sql = bool(pending or not plan)
        prepared.append((outcome, confirmed, calculated, needs_sql, count))
        if needs_sql:
            if 'rows_pickle' in record:
                # Only bytes produced by our trusted spawned kernel, never a
                # network response or Redis value, may enter pickle.loads.
                data = {**data, 'rows': pickle.loads(record['rows_pickle'])}
            sql.append(dict(envelope=envelope,
                normalized=catalog.fingerprint_subset(envelope, data, pending),
                writer=worker.states.writer(catalog, data)))
    if sql:
        metrics.add(project, sql_attempts=len(sql))
        with metrics.span(project, 'sql'):
            # Any member failure rolls back all SQL members. No cache, progress
            # or ACK is published before this single formal transaction returns.
            results = iter(await worker.mysql.archive(sql))
        metrics.add(project, sql_successes=len(sql))
    confirmed_all, outcomes = {}, []
    for outcome, confirmed, calculated, needs_sql, count in prepared:
        if needs_sql:
            outcome = next(results)
            if outcome['confirmed'] and outcome.get('reset_fingerprints'):
                await worker.fingerprints.invalidate(namespace, source)
                if len(records) > 1:
                    raise ValueError('独立单元声明不能重置整个来源摘要；消息保留')
            metrics.add(project, written=outcome.get('written_count', 0) or 0)
            confirmed.update((ident, calculated[ident]) for ident in outcome['confirmed'])
            outcome['row_count'] = count
        confirmed_all.update(confirmed)
        outcomes.append(outcome)
    with metrics.span(project, 'cache_write'):
        await worker.fingerprints.put(namespace, source, confirmed_all)
    return outcomes
