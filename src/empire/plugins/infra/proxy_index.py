"""Rebuildable exit indexes and bounded per-site ready/timer heaps.

Only the pool owns mutations. Selection still requires an atomic Redis lease
check; this index is never proof that a directory candidate is current.
"""
from collections import defaultdict
from heapq import heappop, heappush
from time import monotonic


class SiteIndex:
    def __init__(self, owner, site):
        self.owner, self.site = owner, site
        self.ready, self.timers = [], []
        self.generations = {}
        self.operations = 0

    def update(self, exit_ip, now):
        generation = self.generations.get(exit_ip, 0) + 1
        self.generations[exit_ip] = generation
        self.operations += 1
        if self.owner.busy[self.site].get(exit_ip):
            return
        entries = self.owner.exits.get(exit_ip, {}).values()
        available, deadlines = [], []
        for entry in entries:
            if entry.expires <= now or entry.code in self.owner.retiring:
                continue
            when = max(entry.cooldown, entry.ready_at.get(self.site, 0))
            if when <= now:
                available.append(entry)
            elif when < entry.expires:
                deadlines.append(when)
        if available:
            entry = min(available, key=lambda e: (e.requests, e.last_used, e.code))
            heappush(self.ready, (entry.requests, entry.last_used, entry.code, exit_ip, generation))
        if deadlines:
            heappush(self.timers, (min(deadlines), exit_ip, generation))

    def compact(self, now):
        # Repeated deferrals/releases cannot grow stale heap entries forever.
        if len(self.ready) + len(self.timers) > max(64, 4 * len(self.owner.exits)):
            self.ready.clear()
            self.timers.clear()
            for exit_ip in self.owner.exits:
                self.update(exit_ip, now)

    def take(self, excluded, now):
        while self.timers and self.timers[0][0] <= now:
            _, exit_ip, generation = heappop(self.timers)
            if self.generations.get(exit_ip) == generation:
                self.update(exit_ip, now)
        skipped = []
        try:
            while self.ready:
                item = heappop(self.ready)
                self.operations += 1
                _, _, code, exit_ip, generation = item
                if self.generations.get(exit_ip) != generation:
                    continue
                candidates = [e for e in self.owner.exits.get(exit_ip, {}).values()
                    if e.expires > now and e.cooldown <= now
                    and e.ready_at.get(self.site, 0) <= now and e.code not in self.owner.retiring]
                if not candidates:
                    self.update(exit_ip, now)
                    continue
                eligible = [e for e in candidates if e.code not in excluded]
                if not eligible:
                    skipped.append(item)
                    continue
                entry = min(eligible, key=lambda e: (e.requests, e.last_used, e.code))
                return entry
            return None
        finally:
            for item in skipped:
                heappush(self.ready, item)
            self.compact(now)

    def deadline(self):
        while self.timers and self.generations.get(self.timers[0][1]) != self.timers[0][2]:
            heappop(self.timers)
        return self.timers[0][0] if self.timers else float('inf')


class ExitIndex:
    def __init__(self):
        self.exits = {}
        self.sites = {}
        self.busy = defaultdict(dict)
        self.retiring = set()
        self.health = {}
        self.health_timers = []
        self.healthy = 0
        self.sequence = 0

    def sync(self, entries, retired):
        self.exits = {}
        for entry in entries.values():
            self.exits.setdefault(entry.exit_ip, {})[entry.code] = entry
        self.retiring = {e.code for e in retired if e.busy}
        self.health.clear()
        self.health_timers.clear()
        self.healthy = 0
        now = monotonic()
        for exit_ip in self.exits:
            self.update_health(exit_ip, now)
        # Directory discovery is periodic O(N); allocations never rebuild it.
        for site in self.sites.values():
            site.generations.clear()
            site.ready.clear()
            site.timers.clear()
            for exit_ip in self.exits:
                site.update(exit_ip, now)

    def update_health(self, exit_ip, now):
        previous = self.health.get(exit_ip, (False, 0))[0]
        entries = self.exits.get(exit_ip, {}).values()
        healthy, deadlines = False, []
        for entry in entries:
            if entry.expires > now:
                healthy |= entry.cooldown <= now
                deadlines.append(entry.cooldown if entry.cooldown > now else entry.expires)
        self.sequence += 1
        self.health[exit_ip] = (healthy, self.sequence)
        self.healthy += int(healthy) - int(previous)
        if deadlines:
            heappush(self.health_timers, (min(deadlines), exit_ip, self.sequence))

    def healthy_count(self):
        now = monotonic()
        while self.health_timers and self.health_timers[0][0] <= now:
            _, exit_ip, sequence = heappop(self.health_timers)
            if self.health.get(exit_ip, (False, 0))[1] == sequence:
                self.update_health(exit_ip, now)
        return self.healthy

    def site(self, name):
        if name not in self.sites:
            index = self.sites[name] = SiteIndex(self, name)
            now = monotonic()
            for exit_ip in self.exits:
                index.update(exit_ip, now)
        return self.sites[name]

    def changed(self, exit_ip):
        now = monotonic()
        self.update_health(exit_ip, now)
        if len(self.health_timers) > max(64, 4 * len(self.exits)):
            self.health_timers.clear()
            for current in self.exits:
                self.update_health(current, now)
        for site in self.sites.values():
            site.update(exit_ip, now)
            site.compact(now)

    def reserve(self, entry, site):
        self.busy[site][entry.exit_ip] = self.busy[site].get(entry.exit_ip, 0) + 1
        self.site(site).update(entry.exit_ip, monotonic())

    def release(self, entry, site):
        count = self.busy[site].get(entry.exit_ip, 0) - 1
        if count > 0:
            self.busy[site][entry.exit_ip] = count
        else:
            self.busy[site].pop(entry.exit_ip, None)
        if not entry.busy:
            self.retiring.discard(entry.code)
        self.changed(entry.exit_ip)
