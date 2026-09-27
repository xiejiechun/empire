import pytest

from empire.plugins.collection.control import validate_policy
from empire.plugins.infra.proxy_pool import parse_endpoint


def test_runtime_rejects_retired_minutes():
    old = {"enabled": True, "mode": "interval", "interval_minutes": 5,
           "daily_time": "18:00", "request_retries": 2}
    with pytest.raises(ValueError, match="维护"):
        validate_policy(old)


@pytest.mark.parametrize("raw", ["socks5h://user:secret@localhost:1", "user:secret@localhost:1"])
def test_old_proxy_directory_is_rejected_without_credentials(raw):
    with pytest.raises(ValueError) as error:
        parse_endpoint("node001", raw, 180)
    assert "secret" not in str(error.value)
