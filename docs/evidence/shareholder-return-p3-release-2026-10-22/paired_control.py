"""One unchanged exact-prechange measurement; no candidate acceptance claim."""
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
BASE = ROOT / 'build/returns-p3-20261022/prechange'
sys.path[:0] = [str(BASE / 'scripts'), str(BASE / 'src')]
import source_verification as verification
from repurchase_capacity import RepurchaseCapacityStorage
from measure_repurchases import measure
from source_test_storage import read_server_uuid, test_settings
from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from PySide6.QtCore import QCoreApplication

async def main():
    assert project_root() == BASE
    output, report = verification.initial_report(SimpleNamespace(output=str(BASE/'build/paired-prechange-20261022.json')), 'capacity_control')
    cfg = load_config(ROOT/'config.toml')
    settings_path = ROOT/'build/architecture-evolution-20261019/mysql-settings.json'
    settings = test_settings(json.loads(settings_path.read_text('utf8')))
    seed_path = ROOT/'build/returns-p3-20261022/private-source.json'
    seed = json.loads(seed_path.read_text('utf8'))['first']
    storage = lock = None
    redactor = Redactor.from_config(cfg)
    report.update(control='exact prechange e204cfb; unchanged measure API; same seed and service; no source request', source_sha256=source_digest(BASE))
    report['input_files'] = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (settings_path, ROOT/'config.toml', seed_path)}
    try:
        lock = acquire_instance_lock()
        storage = RepurchaseCapacityStorage(settings,cfg['redis'],report['run_id'],token_hex(32),read_server_uuid(cfg['mysql']))
        redactor = Redactor([*redactor.secrets,storage.owner])
        ownership = output.with_name(output.name+'.ownership.json')
        verification.write_ownership(ownership,storage,str(settings_path))
        storage.create_sql(before_create=lambda:verification.write_ownership(ownership,storage,str(settings_path)))
        report['storage'] = storage.identity()
        await storage.create_redis()
        storage.seed([],[])
        cpu, wall = time.process_time(), time.perf_counter()
        measured = await asyncio.to_thread(measure,storage,seed)
        report.update(measured)
        report['diagnostic_total'] = dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall)
        verification.require(all(measured['measurements'][k]<=v for k,v in measured['limits'].items()),'Prechange exceeds frozen thresholds')
        report.update(pipeline_verified=True,acceptance_complete=True)
    except BaseException as exc:
        report['errors'].append(dict(stage='control',message=redactor.text(exc,2048)))
    finally:
        passed = await verification.complete(output,report,redactor,None,storage,lock,False)
    (OUT/'paired-prechange.json').write_bytes(output.read_bytes())
    print('PASS' if passed else 'FAIL')
    return 0 if passed else 1

app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
raise SystemExit(asyncio.run(main()))
