"""Diagnostic only: profile unchanged capacity API, never acceptance evidence."""
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'scripts'))
import repurchase_capacity as api
original = api.measure

def diagnostic(*args):
    profile = cProfile.Profile()
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        profile.enable()
        return original(*args)
    finally:
        profile.disable()
        profile.dump_stats(str(OUT / 'capacity-profile.pstats'))
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(65)
        (OUT / 'capacity-profile.txt').write_text(stream.getvalue(), encoding='utf8')
        (OUT / 'profile-timing.json').write_text(json.dumps(dict(
            diagnostic_only=True, wall_seconds=time.perf_counter()-wall,
            cpu_seconds=time.process_time()-cpu), indent=2))

api.measure = diagnostic
raise SystemExit(api.main())
