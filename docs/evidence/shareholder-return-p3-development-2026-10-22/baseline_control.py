"""Execute the unchanged pre-change capacity API; never patch a measured tool."""
import asyncio, hashlib, json, sys
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
ORIGINAL=Path(__file__).resolve().parents[2]
BASE=Path(__file__).parent/'prechange'
sys.path[:0]=[str(BASE/'scripts'),str(BASE/'src')]
import source_verification as verification
from repurchase_capacity import RepurchaseCapacityStorage
from measure_repurchases import measure
from source_test_storage import read_server_uuid,test_settings
from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config,project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from PySide6.QtCore import QCoreApplication

async def main():
    assert project_root()==BASE
    output,report=verification.initial_report(SimpleNamespace(output=str(BASE/'build/control.json')),'capacity_control')
    cfg=load_config(ORIGINAL/'config.toml')
    settings_path=ORIGINAL/'build/architecture-evolution-20261019/mysql-settings.json'
    settings=test_settings(json.loads(settings_path.read_text('utf8')))
    seed_proof=ORIGINAL/'build/returns-p3-20261022/private-source.json'
    seed=json.loads(seed_proof.read_text('utf8'))['first']
    redactor=Redactor.from_config(cfg); storage=lock=None
    report.update(control='prechange e204cfb git archive; unchanged original measure function and thresholds; no new source request',source_sha256=source_digest(BASE))
    report['input_files']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [settings_path,ORIGINAL/'config.toml',seed_proof]}
    try:
        lock=acquire_instance_lock()
        storage=RepurchaseCapacityStorage(settings,cfg['redis'],report['run_id'],token_hex(32),read_server_uuid(cfg['mysql']))
        redactor=Redactor([*redactor.secrets,storage.owner])
        own=output.with_name(output.name+'.ownership.json')
        verification.write_ownership(own,storage,str(settings_path))
        storage.create_sql(before_create=lambda:verification.write_ownership(own,storage,str(settings_path)))
        report['storage']=storage.identity()
        await storage.create_redis();storage.seed([],[])
        result=await asyncio.to_thread(measure,storage,seed)
        report.update(result)
        verification.require(all(result['measurements'][k]<=limit for k,limit in result['limits'].items()),'Prechange control exceeds unchanged thresholds')
        report.update(pipeline_verified=True,acceptance_complete=True)
    except BaseException as exc:report['errors'].append(dict(stage='baseline_control',message=redactor.text(exc,2048)))
    finally:passed=await verification.complete(output,report,redactor,None,storage,lock,False)
    print('PASS' if passed else 'FAIL')
    return 0 if passed else 1
app=QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
raise SystemExit(asyncio.run(main()))
