from pathlib import Path
r=Path('src/empire/features')
def e(f,a,b):
 p=r/f;s=p.read_text(encoding='utf-8');assert a in s,(f,a);p.write_text(s.replace(a,b,1),encoding='utf-8')
e('capital_actions/dividend_discovery.py','    securities = sorted(stocks)',"    securities = sorted(stocks)\n    c.stats.update(completed_units=0, total_units=len(securities), unit_name='只股票（历史目录核验）')")
e('capital_actions/dividend_discovery.py','            keys[securities[index]] = identities',"            keys[securities[index]] = identities\n            c.stats['completed_units'] = index + 1")
e('performance/collector.py',"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['index'], total_units=cursor['index'])\n            stage = 'archive_confirmation'")
e('unlock_industries/collector.py',"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['index'], total_units=len(cursor['months']))\n            stage = 'archive_confirmation'")
e('unlocks/collector.py',"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['index'], total_units=cursor['index'])\n            stage = 'archive_confirmation'")
e('yuanhang/collector.py',"self.stats.update(status='complete', planned_requests=0, skipped_units=len(codes))", "self.stats.update(status='complete', planned_requests=0, skipped_units=len(codes),\n                                  completed_units=len(codes), total_units=len(codes))")
# Dynamic plans: distinguish exact whole-run counts from bounded batches whose rest is not enumerated.
f='yuanhang_limits/collector.py'
e(f,"            plan = cursor['plan']", "            self._progress(cursor)\n            plan = cursor['plan']")
e(f,"                    self.stats.update(completed_units=cursor['page'],", "                    self._progress(cursor)\n                    self.stats.update(")
e(f,"        if cursor['page']:", "        self._progress(cursor, finished=True)\n        if cursor['page']:")
e(f,'    async def stop(self):', '''    def _progress(self, cursor, *, finished=False):
        index = cursor.get('index', cursor['page'])
        remaining = cursor['remaining']
        if finished:
            done = total = cursor['page']
            unit = '个完整单元'
        elif remaining is None:
            done, total = index, len(cursor['plan'])
            unit = '个单元（当前批）'
        else:
            done = cursor['page']
            total = done + len(cursor['plan']) - index + remaining
            unit = '个完整单元'
        self.stats.update(completed_units=done, total_units=total, unit_name=unit)

    async def stop(self):''')
# News: initial/fresh is exactly one complete page; incremental stop point is discovered while reading.
f='news/collector.py'
e(f,'            while cursor["phase"] == "fetch":', '''            self.stats.update(completed_units=cursor['pages'],
                              total_units=1 if not cursor['high_watermark'] else None, unit_name='页新闻')
            while cursor["phase"] == "fetch":''')
e(f,'                        cursor = state["cursor"]', '''                        cursor = state["cursor"]
                        self.stats['completed_units'] = cursor['pages']''')
e(f,'            self.stats.update(status="awaiting_archive",', '''            self.stats.update(completed_units=cursor['pages'], total_units=cursor['pages'])
            self.stats.update(status="awaiting_archive",''')
