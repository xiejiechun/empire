from pathlib import Path
r=Path('src/empire/features')
def e(f,a,b):
 p=r/f;s=p.read_text(encoding='utf-8');assert a in s,(f,a);p.write_text(s.replace(a,b,1),encoding='utf-8')
e('industries/collector.py',"completed_units=cursor['industries'], total_units=cursor['industries']", "completed_units=cursor.get('industries'), total_units=cursor.get('industries')")
# Clear previous-round counters while a new plan is being resolved; never alter durable cursors.
for f in ['calendar/collector.py','suspensions/collector.py','listing_status/collector.py','industries/collector.py','repurchases/collector.py','themes/collector.py','yuanhang_limits/collector.py']:
 p=r/f;s=p.read_text(encoding='utf-8');pos=s.index('\n',s.index('    async def execute('))+1
 s=s[:pos]+"        self.stats.update(completed_units=0, total_units=None)\n"+s[pos:];p.write_text(s,encoding='utf-8')
for f in ['stocks/ths_collector.py','stocks/sina_collector.py']:
 p=r/f;s=p.read_text(encoding='utf-8');pos=s.index('\n',s.index('    async def execute('))+1
 s=s[:pos]+"        self.stats.update(collected=0, expected_count=None)\n"+s[pos:];p.write_text(s,encoding='utf-8')
# Returning an already completed checkpoint should still restore the count, not show 0/unknown.
for f in ['ths_capital/collector.py','listings/collector.py','financial_statements/collector.py']:
 if f.startswith('financial'): continue
 e(f,"            if progressed and cursor.get('phase') == 'complete':\n                return cursor", "            if progressed and cursor.get('phase') == 'complete':\n                self.stats.update(completed_units=cursor['index'], total_units=cursor['units'])\n                return cursor")
# A zero-work scope isn't an unknown total.
p=Path('desktop/src/RunJournal.tsx');s=p.read_text(encoding='utf-8').replace('percent == null ? "总量尚未确认，暂不计算百分比"', 'percent == null ? (progress.total_units === 0 ? "本轮没有待处理单元" : "总量尚未确认，暂不计算百分比")');p.write_text(s,encoding='utf-8')
p=Path('src/empire/plugins/collection/management_query.py');s=p.read_text(encoding='utf-8').replace("'status', 'completed_units', 'processed_units', 'total_units')", "'status', 'completed_units', 'processed_units', 'total_units', 'unit_name')");p.write_text(s,encoding='utf-8')
p=Path('desktop/src/Tasks.tsx');s=p.read_text(encoding='utf-8').replace('title="采集进度；入队完成后仍须等待归档确认"', 'title={`采集进度 · ${r.progress?.unit_name || "完整单元"}；仍须等待本轮完成确认`}');p.write_text(s,encoding='utf-8')
