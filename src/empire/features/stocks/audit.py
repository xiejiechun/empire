"""Business-owned stocks.audit."""
from datetime import datetime

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.stocks.api import current_directory
from empire.features.stocks.audit_rules import audit_stocks
from empire.plugins.infra.collection_state import read_state


def check_stocks(plugin):
    with plugin.mysql.read_engine.connect() as conn:
        state = (current_directory(conn, plugin.namespace) if plugin.project_id == 'current'
                 else read_state(conn, plugin.namespace, plugin.project_id, plugin.source))
        rows = conn.execute(text('''SELECT LEFT(unified_code,6) AS code,name,unified_code,RIGHT(unified_code,2) AS market,
            CONCAT(LOWER(RIGHT(unified_code,2)),LEFT(unified_code,6)) AS source_symbol
            FROM stock LIMIT 100001'''), {'source': plugin.source}).mappings().all()
        return audit_stocks(rows, state, datetime.now(CHINA))
