
import asyncio, os, sys
from empire.core.config import load_config
from empire.bootstrap import build_manager

async def main():
    cfg = load_config(os.environ.get("EMPIRE_CONFIG"))
    cfg["redis"]["namespace"] = sys.argv[1]
    manager = build_manager(cfg)
    archive = manager.entries["pipeline.archive"].plugin
    async def crash(ids):
        os._exit(23)
    archive.acknowledge = crash
    await manager.start("pipeline.archive")
    await asyncio.sleep(20)

asyncio.run(main())
