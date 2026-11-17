"""Plan from trusted annual heads and the bounded recent date window."""
from datetime import date, timedelta


def tail(snapshot):
    start = (date.fromisoformat(snapshot['end']) - timedelta(days=29)).isoformat()
    return [r for r in snapshot['rows'] if r[0] >= start]


def full_years(snapshot, heads, *, fresh=False):
    recent = tail(snapshot)
    years = []
    for year, count in sorted(snapshot['years'].items()):
        head = heads.get(year)
        if head and head['last_date'] > snapshot['end']:
            continue  # A delayed source or early manual cutoff cannot roll SQL back.
        incoming = {r[0] for r in recent if r[0][:4] == year}
        need = fresh or not head or head.get('contract_version') != 1
        if head and not need:
            if incoming:
                window_start = recent[0][0]
                old = set(head.get('dates', ()))
                # A disappeared date, same-count changed set or gap beyond the
                # revision window requires a full source year, never a guess.
                need = (head['last_date'] < window_start
                        or not {d for d in old if d >= window_start} <= incoming
                        or head['row_count'] + len(incoming - old) != count)
            else:
                need = head['row_count'] != count
        if need:
            years.append(int(year))
    return years
