from empire.contracts.collector import IngestPublisher
from empire.contracts.data import Envelope

async def publish(ingest: IngestPublisher, event: Envelope) -> None:
    await ingest.publish_page(
        [event], job_key="job", expected_revison=0, cursor={}
    )
