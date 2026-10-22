"""Record actual commands/exits; documentation-only, no release or package mutation."""
import json,subprocess,sys,time
from datetime import UTC,datetime
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').is_file())
OUT=Path(__file__).parent
commands=[
 ('generate',[sys.executable,'-X','utf8','scripts/documentation_build.py','generate']),
 ('review',[sys.executable,'-X','utf8','scripts/documentation_contract.py','review','--note','跨批次独立验收：P0/P1、P2和P3当前正式记录独立复算、同包真实桌面及正常重启；更新数据准备集中指南，修正旧回购阻断/P3状态措辞；保留原失败，O7可行性已证明产品暂缓，O8暂缓；未修改产品实现或安装包。']),
 ('verify',[sys.executable,'-X','utf8','scripts/verify_documentation.py']),
 ('implementation-unchanged',['git','diff','--exit-code','6808f85','--','src/**/*.py','scripts','tests','sql','Empire.spec','verify-release.ps1']),
 ('whitespace',['git','diff','--check'])]
results=[]
for label,args in commands:
    started=datetime.now(UTC).isoformat();t=time.perf_counter()
    p=subprocess.run(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (OUT/(label+'.log')).write_bytes(p.stdout)
    results.append(dict(label=label,command=args,at=started,seconds=time.perf_counter()-t,exit_code=p.returncode))
    (OUT/'close-checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(label,p.returncode,p.stdout.decode('utf8',errors='replace')[-1200:],flush=True)
    if p.returncode:sys.exit(p.returncode)
