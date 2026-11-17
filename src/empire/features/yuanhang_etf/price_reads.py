"""Bounded price list/chart reads shared with the observation calendar."""
from datetime import date

from sqlalchemy import text

from empire.features.yuanhang_etf.contract import day, security
from empire.features.yuanhang_etf.quality import price_relation_valid, volume_amount_valid
from empire.plugins.infra.query_order import column_fields, ordered_page


class PriceReads:
    async def browse(self, code="", start="", end="", after=None, limit=200, order=None):
        if code:
            security(code)
        for value in (start, end):
            if value:
                day(value)
        if start and end and start > end or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("ETF行情查询范围无效")
        params, conditions = dict(limit=limit + 1), []
        for field, value, sql in [
            ("code", code, "p.unified_code=:code"),
            ("start", start, "p.trade_date>=:start"),
            ("end", end, "p.trade_date<=:end"),
        ]:
            if value:
                params[field] = value
                conditions.append(sql)
        if after is not None and order is None:
            if not isinstance(after, (list, tuple)) or len(after) != 2:
                raise ValueError("ETF行情分页游标无效")
            params.update(cursor_date=day(after[0]), cursor_code=security(after[1]))
            conditions.append(
                "(p.trade_date>:cursor_date OR (p.trade_date=:cursor_date AND p.unified_code>:cursor_code))"
            )

        def read():
            with self.mysql.read_engine.connect() as conn:
                where = " WHERE " + " AND ".join(conditions) if conditions else ""
                if order is not None:
                    fields = column_fields(('unified_code', 'name', 'trade_date',
                                            'open', 'high', 'low', 'close', 'volume', 'amount'))
                    # Each comparison with missing operands is false, as in the
                    # existing source-quality functions; missing values stay missing.
                    fields['price_relation_valid'] = 'NOT (' + ' OR '.join(
                        'COALESCE(' + term + ',FALSE)' for term in (
                            'q.low>q.high', 'q.open<q.low', 'q.close<q.low',
                            'q.open>q.high', 'q.close>q.high',
                        )) + ')'
                    fields['volume_amount_valid'] = '(COALESCE(q.volume>=0,TRUE) AND COALESCE(q.amount>=0,TRUE))'
                    values, cursor = ordered_page(
                        conn, 'SELECT p.*,i.name FROM yuanhang_etf_daily_price p LEFT JOIN yuanhang_etf i '
                        'ON i.unified_code=p.unified_code' + where,
                        {k: v for k, v in params.items() if k != 'limit'}, order=order,
                        fields=fields, identity=('unified_code', 'trade_date'), after=after, limit=limit,
                    )
                    for row in values:
                        row['price_relation_valid'] = price_relation_valid([row[k] for k in ('open', 'high', 'low', 'close')])
                        row['volume_amount_valid'] = volume_amount_valid([row['volume'], row['amount']])
                    return dict(rows=values, next=cursor)
                access = "PRIMARY" if code else "ix_etf_price_date"
                values = (
                    conn.execute(
                        text(
                            "SELECT p.*,i.name FROM yuanhang_etf_daily_price p FORCE INDEX ("
                            + access
                            + ") LEFT JOIN yuanhang_etf i "
                            "ON i.unified_code=p.unified_code"
                            + where
                            + " ORDER BY p.trade_date,p.unified_code LIMIT :limit"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
                rows = [dict(r) for r in values[:limit]]
                for row in rows:
                    row["price_relation_valid"] = price_relation_valid(
                        [row[k] for k in ("open", "high", "low", "close")]
                    )
                    row["volume_amount_valid"] = volume_amount_valid([row["volume"], row["amount"]])
                return dict(
                    rows=rows,
                    next=[rows[-1]["trade_date"].isoformat(), rows[-1]["unified_code"]]
                    if len(values) > limit
                    else None,
                )

        return await self.mysql.read(read)

    async def chart_series(self, code, start, end):
        security(code)
        lower, upper = date.fromisoformat(day(start)), date.fromisoformat(day(end))
        if lower > upper or (upper-lower).days > 14640:
            raise ValueError('图表范围必须有起止日期，最多40年')
        def read():
            with self.mysql.read_engine.begin() as conn:
                data = [dict(r) for r in conn.execute(text('SELECT p.*,i.name FROM yuanhang_etf_daily_price p '
                    'LEFT JOIN yuanhang_etf i ON i.unified_code=p.unified_code WHERE p.unified_code=:code '
                    'AND p.trade_date BETWEEN :start AND :end ORDER BY p.trade_date LIMIT 10001'),
                    dict(code=code, start=lower, end=upper)).mappings()]
                if len(data) > 10000:
                    raise ValueError('ETF图表记录超过10000日，拒绝截断')
                for row in data:
                    row['price_relation_valid'] = price_relation_valid([row[k] for k in ('open', 'high', 'low', 'close')])
                    row['volume_amount_valid'] = volume_amount_valid([row['volume'], row['amount']])
                return dict(rows=data, unified_code=code, start=start, end=end)
        return await self.mysql.read(read)

