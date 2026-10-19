"""Stock snapshot completion protocol; called by the shared confirmation provider."""
from empire.features.stocks.publication import read_snapshot_marker
from empire.plugins.infra.collection_state import CollectionState


async def stock_status(mysql, redis, source, job_key, project_id, snapshot_id):
    confirmed = await redis.client.get(f"{redis.prefix}:stocks:committed:{source}")
    value = read_snapshot_marker(confirmed, "complete")
    if value and value["snapshot_id"] == snapshot_id:
        return value
    if value is None:
        state = await mysql.control(
            CollectionState(mysql, redis.prefix).read, source, project_id)
        committed = state.get("progress", {})
        if committed.get("snapshot_id") == snapshot_id:
            return committed
    result = await redis.client.get(f"{redis.prefix}:stocks:result:{source}")
    value = read_snapshot_marker(result, "invalid")
    return value if value and value["snapshot_id"] == snapshot_id else None
