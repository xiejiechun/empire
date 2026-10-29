from pathlib import Path
# Restore presentation after already-completed short circuit too.
for rel, code in {
 'calendar/collector.py':'self.stats.update(completed_units=cursor["pages"], total_units=len(cursor["months"]), unit_name="个月")',
 'suspensions/collector.py':'self.stats.update(completed_units=cursor["dates_checked"], total_units=(datetime.fromisoformat(cursor["end_date"]) - datetime.fromisoformat(cursor["start_date"])).days + 1, unit_name="个日期")',
 'repurchases/collector.py':"self.stats.update(completed_units=cursor['collected'], total_units=cursor['total'])",
}.items():
 p=Path('src/empire/features')/rel;s=p.read_text(encoding='utf-8');needle='                return self._result(cursor)' if rel[0] in 'cs' else '                return cursor';assert needle in s;s=s.replace(needle,'                '+code+'\n'+needle,1);p.write_text(s,encoding='utf-8')
p=Path('src/empire/features/yuanhang_limits/collector.py');s=p.read_text(encoding='utf-8').replace("        if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':\n            return cursor", "        if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':\n            self._progress(cursor, finished=True)\n            return cursor");p.write_text(s,encoding='utf-8')
# Tests observe genuine existing lifecycle fixtures; no source requests are issued.
for file,needle,extra in [
 ('tests/test_cninfo_calendar.py','    assert result["collected"] == 61 and result["pages"] == 2','    assert item.health()["completed_units"] == item.health()["total_units"] == 2'),
 ('tests/test_cninfo_calendar.py','    assert item.ingest.state["cursor"]["pages"] == 1','    assert item.health()["completed_units"] == 1 and item.health()["total_units"] == 2'),
 ('tests/test_yuanhang_limits_collector.py',"    assert state['cursor']['page'] == 1 and len(events) == 1", "    assert c.health()['completed_units'] == 1 and c.health()['total_units'] == 2"),
 ('tests/test_capital_recovery.py',"    assert c.stats['processed_units'] == 2 and c.stats['failed_units'] == 1", "    assert c.stats['completed_units'] == 1 and c.stats['total_units'] == 2"),
 ('tests/test_ths_holders.py',"    assert c.stats['processed_units'] == 4 and c.stats['failed_units'] == 1", "    assert c.stats['completed_units'] == 3 and c.stats['total_units'] == 4"),
]:
 p=Path(file);s=p.read_text(encoding='utf-8');assert needle in s;s=s.replace(needle,needle+'\n'+extra,1);p.write_text(s,encoding='utf-8')
