"""News identities and pure canonical ID/version contracts."""
import re

from empire.contracts.archive_version import ArchiveVersion

JOB, PROJECT, SOURCE = 'sina-news-v1', 'sina-news', 'sina'
DATASET = 'news.flash.page'
DATASETS = {DATASET}
FINGERPRINT_NAMESPACE = 'news'
FINGERPRINT_VERSION = ArchiveVersion(('utc', 'utc'), observed_index=1, source_indices=(0,))


def news_id(value: str | int) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError("新闻 ID 必须是正整数")
    result = int(value)
    if result > 9223372036854775807:
        raise ValueError("新闻 ID 超出支持范围")
    return result
