from empire.features.market_review.etf_flows import estimate


def test_estimate_exact_zero_negative_and_adjusted_shares():
    result = estimate(
        ["a", "b", "c"],
        dict(a="110", b="10", c="9"),
        dict(a="100", b="10", c="10"),
        {k: dict(value_kind="nav", unit_nav="1.25", currency="CNY") for k in "abc"},
        adjustments=dict(a="5", b="0", c="0"),
    )
    assert result["covered_count"] == 3 and result["amount_yuan"] == "5"


def test_missing_currency_or_event_never_implicitly_cny_or_zero_adjustment():
    r = estimate(
        ["a"],
        dict(a="110"),
        dict(a="100"),
        dict(a=dict(value_kind="nav", unit_nav="1.25", currency=None)),
    )
    assert r["amount_yuan"] is None and r["covered_count"] == 0 and r["candidate_count"] == 1
    assert r["missing"]["unknown_currency"] == r["missing"]["event_review"] == 1


def test_source_absence_income_and_null_nav_not_replaced_by_zero():
    nav = dict(
        b=dict(value_kind="income", income_value="1.1"), c=dict(value_kind="nav", unit_nav=None)
    )
    r = estimate(list("abc"), dict(b="10", c="10"), dict(b="10", c="10"), nav)
    assert r["amount_yuan"] is None and r["missing"]["missing_shares"] == 1
    assert r["missing"]["income_only"] == 1 and r["missing"]["missing_nav"] == 1
