"""Include real pure source parsers and packing in the C measurement window."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date


@asynccontextmanager
async def parsed_sources(catalog, values, sources):
    retained = []

    async def parse(template):
        body, stock = sources[template['business_key']]
        if template['dataset'] == 'ths.capital.security':
            from empire.features.ths_capital.contract import digest
            from empire.features.ths_capital.source import parse
            from empire.features.ths_capital.transport import pack
            if hasattr(catalog, 'compute_source'):
                result = await catalog.compute_source('ths.capital', body, stock, date(2026, 11, 6))
                retained.append(result)
                data = result.value
            else:
                data = parse(body, stock, date(2026, 11, 6))
            digest(data)  # Collector's complete-unit rolling proof cost.
            payload = {**template['payload'], 'rows': pack(data['rows']), 'availability': data['availability']}
        else:
            from empire.features.financial_statements.contract import parse
            from empire.features.financial_statements.wire import pack_rows
            rows = parse('income', body, stock)
            payload = {**template['payload'], 'rows': pack_rows(rows)}
        assert payload == template['payload'], 'source parse changed full fixture contents'
        return {**template, 'payload': payload}

    try:
        # Same independent-security parallelism as the bounded source prefetch;
        # the resulting list is consumed/published in its original order.
        from empire.plugins.infra.sql_lane import settle
        results = []
        for offset in range(0, len(values), 8):
            group = await settle(asyncio.gather(*(parse(value) for value in values[offset:offset + 8]),
                                                return_exceptions=True))
            for value in group:
                if isinstance(value, BaseException):
                    raise value
            results.extend(group)
        yield results
    finally:
        for result in retained:
            result.close()
