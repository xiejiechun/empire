"""Eligibility of the official raw GetStockPanKou snapshot, shared by analyses."""
from empire.features.capital_actions.event_rules import ActionError, decimal


def closing_clock(values, day):
    clock = decimal(values.get('time'))
    if clock != int(clock):
        raise ActionError('行情快照时刻无效，不能认定收盘价', day=day)
    clock = int(clock)
    if not (150000000 <= clock <= 235959999 and clock // 100000 % 100 < 60
            and clock // 1000 % 100 < 60):
        raise ActionError('行情不是有效收盘后快照，不能以最新价替代收盘价', day=day)
    return clock
