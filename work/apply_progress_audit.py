from pathlib import Path
root=Path('src/empire/features')
def edit(file, old, new, count=1):
 p=root/file;s=p.read_text(encoding='utf-8');assert old in s,(file,old);p.write_text(s.replace(old,new,count),encoding='utf-8')
# Each progress value comes from an existing validated plan or committed cursor.
for folder in ['ths_capital','listings']:
 f=folder+'/collector.py'
 edit(f,"        stage = 'plan'", "        self.stats.update(completed_units=0, total_units=None, unit_name='只股票')\n        stage = 'plan'")
 edit(f,"                selected =", "                self.stats.update(completed_units=cursor['index'], total_units=len(keys))\n                selected =")
 edit(f,"                        cursor = state['cursor']", "                        cursor = state['cursor']\n                        self.stats['completed_units'] = cursor['index']")
 edit(f,"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['index'], total_units=cursor['units'])\n            stage = 'archive_confirmation'")
# Months and days, not record counts (a valid empty response still completes a unit).
edit('calendar/collector.py','            if cursor["phase"] == "fetch":','            self.stats.update(completed_units=cursor["pages"], total_units=len(cursor["months"]), unit_name="个月")\n            if cursor["phase"] == "fetch":')
edit('calendar/collector.py','                        cursor = state["cursor"]','                        cursor = state["cursor"]\n                        self.stats["completed_units"] = cursor["pages"]')
edit('suspensions/collector.py','            while cursor["phase"] == "fetch":','            self.stats.update(completed_units=cursor["dates_checked"],\n                total_units=(datetime.fromisoformat(cursor["end_date"]) - datetime.fromisoformat(cursor["start_date"])).days + 1, unit_name="个日期")\n            while cursor["phase"] == "fetch":')
edit('suspensions/collector.py',"                    cursor = state['cursor']", "                    cursor = state['cursor']\n                    self.stats['completed_units'] = cursor['dates_checked']")
edit('listing_status/collector.py',"                for month in plan:","                self.stats.update(completed_units=cursor['pages'], total_units=cursor['pages'] + len(plan), unit_name='个月')\n                for month in plan:")
edit('listing_status/collector.py',"                    cursor = state['cursor']", "                    cursor = state['cursor']\n                    self.stats['completed_units'] = cursor['pages']")
edit('listing_status/collector.py',"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['pages'], total_units=cursor['pages'], unit_name='个月')\n            stage = 'archive_confirmation'")
# Complete response tasks: zero until validated and published; one is not an estimated network percentage.
edit('name_changes/collector.py',"        stage =", "        self.stats.update(total_units=1, completed_units=0, unit_name='次完整响应')\n        stage =")
edit('name_changes/collector.py',"            self.stats.update(status='awaiting_archive'", "            self.stats['completed_units'] = 1\n            self.stats.update(status='awaiting_archive'")
# Directory counts already present on stock services, surface the canonical fields.
for f in ['stocks/ths_collector.py','stocks/sina_collector.py']:
 edit(f,'    def health(self):\n        return dict(self.stats)', "    def health(self):\n        return {**self.stats, 'completed_units': self.stats.get('collected'),\n                'total_units': self.stats.get('expected_count'), 'unit_name': '只股票'}")
# Restored confirmed scopes must also have denominators.
edit('industries/collector.py',"                self.stats['total_units'] = len(industries)","                self.stats.update(total_units=len(industries), completed_units=0, unit_name='个行业')")
edit('industries/collector.py',"            stage = 'archive_confirmation'", "            self.stats.update(completed_units=cursor['industries'], total_units=cursor['industries'], unit_name='个行业')\n            stage = 'archive_confirmation'")
edit('repurchases/collector.py',"            while cursor['phase'] == 'fetch':", "            self.stats.update(completed_units=cursor['collected'], total_units=cursor['total'], unit_name='条回购方案')\n            while cursor['phase'] == 'fetch':")
# Successful units exclude rejected source responses, unlike processed attempts.
edit('holders/collector.py',"processed_units=0, total_units=len(selected)","processed_units=0, completed_units=0, total_units=len(selected)")
edit('holders/collector.py',"self.stats.update(collected=cursor['collected'], processed_units=index + 1,", "self.stats.update(collected=cursor['collected'], processed_units=index + 1, completed_units=index + 1 - len(rejected),")
f='capital_actions/lifecycle.py'
edit(f,"    stage = 'plan'", "    c.stats.update(completed_units=0, total_units=None, unit_name='只证券')\n    stage = 'plan'")
edit(f,"            reusable, previous = {}, {}", "            c.stats.update(completed_units=cursor['index'], total_units=len(keys), unit_name='只证券')\n            reusable, previous = {}, {}")
edit(f,"                    queued_records += len(rows)", "                    queued_records += len(rows)\n                    c.stats['completed_units'] = index + 1 - len(failures)")
edit(f,"        stage = 'archive_confirmation'", "        c.stats.update(completed_units=cursor['index'], total_units=cursor['units'])\n        stage = 'archive_confirmation'")
# Phase-specific source verification counts for dividends before the stock publication plan is known.
f='capital_actions/dividend_history.py'
edit(f,"c.stats.update(total_report_periods=len(periods), downloaded_report_periods=0)","c.stats.update(total_report_periods=len(periods), downloaded_report_periods=0,\n                   total_units=len(periods), completed_units=0, unit_name='个报告期（来源核验）')")
edit(f,"c.stats.update(downloaded_report_periods=index + 1, current_report_period=periods[index])", "c.stats.update(downloaded_report_periods=index + 1, current_report_period=periods[index], completed_units=index + 1)")
# Theme list has a single complete snapshot; detail work uses its explicit plan.
f='themes/collector.py'
edit(f,"    async def collect_list(self, state, previous):", "    async def collect_list(self, state, previous):\n        self.stats.update(total_units=1, completed_units=0, unit_name='份完整题材列表')")
edit(f,"        self.stats['collected'] = len(rows)", "        self.stats.update(collected=len(rows), completed_units=1)")
edit(f,"        self.identities = await self.query.identities()", "        self.stats.update(completed_units=cursor['page'], total_units=len(plan), unit_name='个题材')\n        self.identities = await self.query.identities()")
edit(f,"            if cursor.get('phase') == 'awaiting_archive':", "            if cursor.get('phase') == 'awaiting_archive':\n                self.stats.update(completed_units=cursor['page'],\n                    total_units=len(cursor['plan']) if self.kind != 'list' else 1)")
# Live pool response is one bounded snapshot; idle rounds contain no sampling work.
f='yuanhang_limits/intraday.py'
edit(f,"wire_bytes=0, queued_messages=0, queued_bytes=0, collected=0, storage='redis_only')", "wire_bytes=0, queued_messages=0, queued_bytes=0, collected=0, storage='redis_only',\n        total_units=1, completed_units=0, unit_name='份盘中快照')")
edit(f,"collector.stats.update(status='complete', collected=len(unit['rows']),", "collector.stats.update(status='complete', completed_units=1, collected=len(unit['rows']),")
edit(f,"wire_bytes=0, queued_messages=0, queued_bytes=0, notice=", "wire_bytes=0, queued_messages=0, queued_bytes=0, total_units=0, completed_units=0, notice=")
