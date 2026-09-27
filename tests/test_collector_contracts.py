from mypy import api


def test_ingest_protocol_rejects_misspelled_publish_keyword(tmp_path):
    sample = tmp_path / "bad_collector.py"
    sample.write_text(
        """\
from empire.contracts.collector import IngestPublisher
from empire.contracts.data import Envelope

async def publish(ingest: IngestPublisher, event: Envelope) -> None:
    await ingest.publish_page(
        [event], job_key="job", expected_revison=0, cursor={}
    )
""",
        encoding="utf-8",
    )
    stdout, stderr, status = api.run(["--strict", "--show-error-codes", str(sample)])
    assert status == 1, (stdout, stderr)
    assert "expected_revison" in stdout
    assert "Unexpected keyword argument" in stdout
