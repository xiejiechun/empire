from datetime import datetime

import pytest
from pydantic import ValidationError

from empire.contracts.data import Envelope, make_envelope


def envelope(payload):
    return make_envelope(source="test", dataset="stock.universe.start", business_key="1",
                         job_key="job", run_id="run", batch_id="batch", payload=payload)


def test_replay_identity_is_stable_but_revision_changes():
    first = envelope({"x": 1, "y": 2})
    replay = envelope({"y": 2, "x": 1})
    revision = envelope({"x": 3, "y": 2})
    assert first.event_id == replay.event_id
    assert first.event_id != revision.event_id


def test_naive_timestamp_is_rejected():
    value = envelope({"x": 1}).model_dump()
    value["observed_at"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="timezone"):
        Envelope.model_validate(value)
