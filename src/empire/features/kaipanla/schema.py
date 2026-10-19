"""Business-owned schema; moved declarations retain existing behavior."""
from empire.features.kaipanla.storage_contract import MARKET_TABLES
from empire.plugins.infra.schema_manifest import schema_contract

TABLES, KEYS = schema_contract(MARKET_TABLES)
