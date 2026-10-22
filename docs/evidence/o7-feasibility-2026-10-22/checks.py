"""Sequential documentation-only closeout; stop on any failed check."""
import json
import subprocess
import sys
import time
from datetime import UTC,datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/evidence/o7-feasibility-2026-10-22'
PY=str(ROOT/'.venv/Scripts/python.exe')
commands=[
 ('generate',[PY,'-X','utf8','scripts/documentation_build.py','generate']),
 ('review',[PY,'-X','utf8','scripts/documentation_contract.py','review','--note',
  'O7有界可行性调查：五对象两来源路径，官方公告内单事件有限A正例及日期、关联、并发变化B限制；仅提交研究证据和候选设计，未改产品/生产结构/正式采集器，O7未实现未发布，原失败与既有能力保持。']),
 ('verify',[PY,'-X','utf8','scripts/verify_documentation.py']),
 ('documentation-tests',[PY,'-X','utf8','-m','pytest','tests/test_documentation_build.py',
  'tests/test_documentation_review.py','tests/test_documentation_contracts.py',
  'tests/test_documentation_sources.py','tests/test_storage_help.py','-q',
  '--basetemp=build/pytest-o7-feasibility-docs','--junitxml='+str(OUT/'documentation.xml')]),
 ('diff',['git','diff','--check'])]
results=[]
for name,command in commands:
 began=datetime.now(UTC).isoformat();t=time.perf_counter()
 proc=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 (OUT/(name+'.log')).write_bytes(proc.stdout)
 results.append(dict(name=name,command=command,at=began,seconds=time.perf_counter()-t,exit_code=proc.returncode,log=name+'.log'))
 (OUT/'documentation-checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
 print(name,proc.returncode,flush=True)
 if proc.returncode: sys.exit(proc.returncode)
