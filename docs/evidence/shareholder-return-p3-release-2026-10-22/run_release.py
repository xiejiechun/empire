"""Record invocation of the sole formal release entry, without altering it."""
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
assert head=='6808f85188be0aae58c897b417e5819a9e6da529'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
command=['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/'verify-release.ps1')]
env={**os.environ,'EMPIRE_TEST_MYSQL_SETTINGS':str(ROOT/'build/architecture-evolution-20261019/mysql-settings.json')}
record=dict(started_at=datetime.now(UTC).isoformat(),head=head,command=command)
with (OUT/'release.log').open('xb') as stream:
    result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
record.update(finished_at=datetime.now(UTC).isoformat(),returncode=result.returncode,
    final_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
with (OUT/'release-exit.json').open('x',encoding='utf8') as stream:json.dump(record,stream,indent=2)
print(record)
raise SystemExit(result.returncode)
