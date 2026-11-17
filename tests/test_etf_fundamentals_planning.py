from datetime import date, timedelta

from empire.features.etf_fundamentals import planning
from empire.features.etf_fundamentals.contract import CONTRACT


class Heads:
    def __init__(self, values):
        self.values = values

    def execute(self, *_args, **_kwargs):
        return self

    def mappings(self):
        return iter(self.values)


def setup(monkeypatch, *, end="2026-11-16", complete_years=True, recent_end="2026-11-13"):
    code = "510300.SH"
    catalog = [dict(code=code, name="ETF", native_market="USHJ")]
    last = date.fromisoformat(end)
    trades = [
        (last - timedelta(days=i)).isoformat()
        for i in range(14, -1, -1)
        if (last - timedelta(days=i)).weekday() < 5
    ]
    stamp = "2026-10-15T00:00:00.000000+00:00"
    ranges, heads = {}, []
    if complete_years:
        for y in range(2004, 2026):
            ranges[str(y)] = [[max("2004-12-30", f"{y}-01-01"), f"{y}-12-31", stamp]]
            heads.append(
                dict(
                    unified_code=code,
                    nav_year=y,
                    verified_through=date(y, 12, 31),
                    contract_version=CONTRACT,
                )
            )
    if recent_end:
        ranges["2026"] = [["2026-11-01", recent_end, stamp]]
        heads.append(
            dict(unified_code=code, nav_year=2026, verified_through=None, contract_version=CONTRACT)
        )
    monkeypatch.setattr(planning, "scope", lambda conn, end=None: (last.isoformat(), trades))
    monkeypatch.setattr(
        planning, "read_state", lambda *args: dict(units={code: dict(ranges=ranges)})
    )
    return Heads(heads), catalog, trades


def test_recent_partial_year_never_downloads_old_full_history(monkeypatch):
    conn, catalog, trades = setup(monkeypatch)
    plan = planning.nav_plan(conn, "test", catalog)
    recent = [u for u in plan["units"] if u["through"] == "2026-11-16"]
    assert recent
    assert all(u["start"] >= "2026-01-01" for u in recent)
    assert any(u["start"] == trades[-10] for u in recent)
    # The hole before November is a separate bounded historical repair.
    assert any(u["start"] == "2026-01-01" and u["through"] == "2026-10-31" for u in plan["units"])


def test_long_outage_starts_after_last_observed_range(monkeypatch):
    conn, catalog, _ = setup(monkeypatch, end="2027-02-01", recent_end="2026-11-13")
    plan = planning.nav_plan(conn, "test", catalog)
    assert any(u["start"] == "2026-11-14" and u["through"] == "2027-02-01" for u in plan["units"])
    assert not any(
        u["start"] < "2026-01-01" and u["through"] == "2027-02-01" for u in plan["units"]
    )


def test_initialization_keeps_one_full_history_request_per_selected_security(monkeypatch):
    conn, catalog, _ = setup(monkeypatch, complete_years=False, recent_end=None)
    plan = planning.nav_plan(conn, "test", catalog)
    assert plan["units"] == [dict(code="510300.SH", start="2004-12-30", through="2026-11-16")]


def test_monthly_old_revision_does_not_starve_behind_unfinished_history(monkeypatch):
    conn, catalog, _ = setup(monkeypatch)
    plan = planning.nav_plan(conn, "test", catalog)
    assert any(u["start"] < "2026-01-01" for u in plan["units"])
