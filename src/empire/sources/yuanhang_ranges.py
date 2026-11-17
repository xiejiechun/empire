"""Calendar-day authority/version intervals; no I/O or inferred empty responses.

A source-validated range authorizes replacement only inside its bounds. Version
segments include absent trading days, so an old response cannot resurrect a row
deleted by a newer authoritative range. At most 366 segments exist per year.
"""
from datetime import UTC, date, datetime, timedelta


def _day(value, year):
    result = date.fromisoformat(value)
    if result.isoformat() != value or result.year != year:
        raise ValueError('Range date outside annual unit')
    return result


def _version(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.astimezone(UTC).isoformat(timespec='microseconds') != value:
        raise ValueError('Range version must be canonical UTC')
    return value


def validated_segments(segments, year):
    if type(year) is not int or not 1900 <= year <= 2100:
        raise ValueError('Invalid range year')
    if not isinstance(segments, list) or len(segments) > 366:
        raise ValueError('Annual range versions exceed limit')
    result = []
    previous_end, previous_version = None, None
    for segment in segments:
        if not isinstance(segment, list) or len(segment) != 3:
            raise ValueError('Invalid range version segment')
        first, last = (_day(v, year) for v in segment[:2])
        version = _version(segment[2])
        if first > last or (previous_end is not None and first <= previous_end):
            raise ValueError('Range versions overlap or are unsorted')
        if previous_end is not None and first == previous_end + timedelta(days=1) and version == previous_version:
            raise ValueError('Adjacent equal range versions must be coalesced')
        result.append((first, last, version))
        previous_end, previous_version = last, version
    return result


def versions_on(segments, year, days):
    """Validate all segments, materializing only the requested calendar dates."""
    ranges = validated_segments(segments, year)
    return {day: version for day in days for first, last, version in ranges
            if first.isoformat() <= day <= last.isoformat()}


def expand_versions(segments, year):
    result = {}
    for first, last, version in validated_segments(segments, year):
        current = first
        while current <= last:
            result[current.isoformat()] = version
            current += timedelta(days=1)
    return result


def compact_versions(versions):
    result = []
    for day, version in sorted(versions.items()):
        if (result and result[-1][2] == version
                and date.fromisoformat(day) == date.fromisoformat(result[-1][1]) + timedelta(days=1)):
            result[-1][1] = day
        else:
            result.append([day, day, version])
    return result


def replace_range(existing, incoming, *, year, start, end, observed, segments):
    """Return annual rows, versions and accepted days, preserving newer overlaps.

    Caller must validate source identity/fields and the complete response before
    using this function. Empty incoming is permitted only for a year split from
    a nonempty, validated response; a bare empty frame is never such evidence.
    """
    first, last = _day(start, year), _day(end, year)
    if first > last:
        raise ValueError('Inverted range')
    version = _version(observed)
    versions = expand_versions(segments, year)
    def indexed(rows, bounded):
        if not isinstance(rows, list) or len(rows) > 366:
            raise ValueError('Annual rows exceed limit')
        result = {}
        previous = ''
        for row in rows:
            day = _day(row[0], year)
            if row[0] <= previous or (bounded and not first <= day <= last):
                raise ValueError('Unsorted, duplicate or out-of-range row')
            result[row[0]] = row
            previous = row[0]
        return result
    old, new = indexed(existing, False), indexed(incoming, True)
    current, accepted = first, []
    while current <= last:
        key = current.isoformat()
        prior = versions.get(key)
        if prior is None or version >= prior:
            # A single observed version cannot mean two different source facts.
            if prior == version and old.get(key) != new.get(key):
                raise ValueError('Conflicting content at identical observed version')
            accepted.append(key)
            versions[key] = version
            if key in new:
                old[key] = new[key]
            else:
                old.pop(key, None)
        current += timedelta(days=1)
    return [old[k] for k in sorted(old)], compact_versions(versions), accepted


def contiguous_through(segments, year):
    """Coverage requires every calendar day from January 1; quote count is irrelevant."""
    ranges = validated_segments(segments, year)
    current = date(year, 1, 1)
    through = None
    for first, last, _ in ranges:
        if first != current:
            break
        through = last.isoformat()
        current = last + timedelta(days=1)
    return through
