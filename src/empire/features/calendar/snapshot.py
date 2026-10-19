"""Business-owned calendar.snapshot."""
from sqlalchemy import text

from empire.plugins.infra.collection_state import read_state


def calendar_snapshot(plugin):
    with plugin.mysql.read_engine.connect() as conn:
        rows = conn.execute(text('''SELECT trade_date,is_trade FROM trade_calendar
            ORDER BY trade_date LIMIT 20001'''), {'source': plugin.source}).mappings().all()
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        return rows, state
