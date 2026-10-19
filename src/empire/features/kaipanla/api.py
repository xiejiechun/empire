"""Public connection-local read contract; the caller owns its SQL snapshot."""
from collections.abc import Iterator
from datetime import date
from typing import Protocol, TypedDict

from sqlalchemy.engine import Connection

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class Lifecycle(TypedDict):
    listing_date: str
    listing_source: str
    market_start: str


class AliasProof(TypedDict):
    source: str
    current_code: str
    legacy_code: str
    isin: str
    listing_date: str


class SecurityDay(TypedDict):
    kind: str
    code: str
    market: str
    trade_date: str
    source_code: str | None
    aliases: dict[str, AliasProof]
    data: dict[str, JsonValue]
    lifecycle: Lifecycle
    metadata: dict[str, JsonValue]


class ValidatedDayReader(Protocol):
    def iter_validated_days(self, conn: Connection, market: str, code: str,
                            start: date, end: date) -> Iterator[SecurityDay]:
        """Yield <=10000 validated days; never acquire/close conn or a transaction.

        Iteration may fail on malformed content/version; no later days are read
        after the consumer aborts. Consume inside the caller's connection scope.
        """
        ...
