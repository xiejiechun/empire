"""Client fixdata date/item positional contract, independent of the web page limit."""

from empire.features.market_margin.contract import number, validate

URL = "https://data.10jqka.com.cn/rzrq/fixdata/type/{code}/"
PAGE = "https://zx.10jqka.com.cn/rzrq/html/index.html#index"
KEYS = ("rzye", "rqye", "rzmre", "rzjmr", "rqjmc", "jmrzz", "jmczz", "zb", "lr")


def parse(body, through, code):
    if (
        not isinstance(body, dict)
        or type(body.get("status_code")) is not int
        or body["status_code"] != 0
    ):
        raise ValueError("同花顺市场融资融券返回失败")
    data = body.get("data")
    if not isinstance(data, dict) or set(data) != {"date", "item"}:
        raise ValueError("市场历史结构改变")
    dates, items = data["date"], data["item"]
    if not isinstance(dates, list) or not isinstance(items, list) or len(dates) != len(items):
        raise ValueError("市场日期与数值集合长度不一致")
    rows = []
    expected = set(KEYS) if code == "99" else set(KEYS) - {"lr"}
    for stamp, item in zip(dates, items, strict=True):
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("市场数值字段缺失或改变")
        values = []
        for i, key in enumerate(KEYS):
            v = item.get(key)
            if i >= 5 and v in (None, "", "--"):
                v = None
            values.append(number(v, optional=i >= 5, ratio=i == 7))
        rows.append([stamp, *values])
    return validate(rows, through, code)
