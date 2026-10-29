"""Read page declarations only; never start services or read real credentials."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts.assembly_contract import snapshot

declarations = snapshot(ROOT)
pages = declarations["semantic"]["pages"]
target = Path(__file__).resolve().parents[1] / "route-inventory.json"
target.write_text(json.dumps({
    "status": "migration_inventory_not_implementation",
    "source": "scripts.assembly_contract.snapshot using config/app.example.toml",
    "count": len(pages),
    "catalogued_count": sum(bool(page["catalogued"]) for page in pages.values()),
    "pages": pages,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"count": len(pages), "path": str(target)}, ensure_ascii=False))
