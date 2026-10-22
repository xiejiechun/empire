"""Synthetic theme failure using freshly queried real independent outputs; no production mutation."""
import asyncio, json
from copy import deepcopy
from datetime import UTC,datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from empire.features.preparation.products import attach_products
async def main():
    p=Path(__file__).parent
    r=json.loads((p/'current.json').read_text('utf8'))
    report=dict(rows=[dict(id='dividends',required=True),dict(id='repurchases',complete=False)],research=dict(ready=False))
    service=SimpleNamespace(distribution_summary=AsyncMock(return_value=deepcopy(r['cases']['main']['distribution'])),dividend_yield=AsyncMock(return_value=deepcopy(r['cases']['main']['yield_result'])))
    context=SimpleNamespace(optional=lambda k: service if k=='dividends.query' else None)
    scope=dict(codes=['000001'],start='2026-01-01',end='2026-10-20')
    await attach_products(report,context,scope)
    assert not report['research']['ready']
    assert [x['state'] for x in report['products']]==['已计算','已计算','功能未实现','功能未实现','功能未实现']
    service.dividend_yield.return_value=deepcopy(r['cases']['002731']['yield_result'])
    service.distribution_summary.return_value=deepcopy(r['cases']['002731']['distribution'])
    await attach_products(report,context,{**scope,'codes':['002731']})
    assert [x['state'] for x in report['products'][:2]]==['已计算','数据阻断']
    service.dividend_yield.return_value=deepcopy(r['cases']['historical']['yield_result'])
    service.distribution_summary.return_value=deepcopy(r['cases']['historical']['distribution'])
    await attach_products(report,context,{**scope,'purpose':'historical_signal'})
    assert [x['state'] for x in report['products'][:2]]==['来源受限','来源受限']
    result=dict(at=datetime.now(UTC).isoformat(),mode='synthetic theme failure; real query outputs; no fault injected into production',main_states=['已计算','已计算'],missing_price_states=['已计算','数据阻断'],historical_states=[x['state'] for x in report['products'][:2]],theme_ready=report['research']['ready'])
    (p/'cross-effects.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
