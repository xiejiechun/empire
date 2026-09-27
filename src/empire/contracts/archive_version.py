"""Dataset-owned archive version contracts, shared by cache and comparison."""
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from empire.core.time import CHINA


@dataclass(frozen=True)
class ArchiveVersion:
    parts: tuple[str, ...]
    observed_index: int
    source_indices: tuple[int, ...] = ()

    def key(self, value, *, now=None, trusted=True):
        """Reject noncanonical proofs; compare parsed times, never arbitrary strings.

        Five minutes tolerates a small clock correction. Source revisions farther
        ahead of observation are not cache evidence, but remain valid SQL input:
        trusted=False checks structure only and never rejects source data for drift.
        """
        if (not isinstance(value, list) or len(value) != len(self.parts)
                or any(not isinstance(part, str) or not part for part in value)):
            raise ValueError("归档版本维数或字段无效")
        result = []
        for kind, part in zip(self.parts, value):
            if kind == "snapshot":
                if not re.fullmatch(r"[0-9a-f]{32}", part):
                    raise ValueError("归档批次版本无效")
                result.append(part)
                continue
            parsed = datetime.fromisoformat(part)
            if kind == "utc":
                canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds") if parsed.tzinfo else None
            elif kind == "china":
                canonical = parsed.isoformat(timespec="microseconds") if parsed.tzinfo is None else None
                parsed = parsed.replace(tzinfo=CHINA).astimezone(UTC)
            else:
                raise ValueError("未声明的归档版本字段")
            if part != canonical:
                raise ValueError("归档版本时间不是声明的规范格式")
            result.append(parsed)
        if trusted:
            observed = result[self.observed_index]
            if observed > (now or datetime.now(UTC)) + timedelta(minutes=5):
                raise ValueError("归档本地观测版本超前，须回源核对")
            if any(result[index] > observed + timedelta(minutes=5) for index in self.source_indices):
                raise ValueError("来源版本超前于观测，须回源核对")
        return tuple(result)

    def compare(self, left, right):
        first, second = self.key(left, trusted=False), self.key(right, trusted=False)
        return (first > second) - (first < second)
