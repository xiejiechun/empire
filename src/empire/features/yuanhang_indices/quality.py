"""Derived source quality; missing observations remain missing."""
from decimal import Decimal


def price_relation_valid(values):
    op, high, low, close = [Decimal(v) if v is not None else None for v in values]
    return not (
        high is not None and low is not None and low > high
        or low is not None and any(v is not None and v < low for v in (op, close))
        or high is not None and any(v is not None and v > high for v in (op, close)))


def volume_amount_valid(values):
    return all(v is None or Decimal(v) >= 0 for v in values)
