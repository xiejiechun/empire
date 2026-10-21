"""Versioned acceptance criteria; unknown or missing evidence never passes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    id: str
    title: str
    expected: str
    action: str


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    category: str
    priority: str
    purpose: str
    grain: str
    fields: str
    key: str
    coverage: str
    cadence: str
    dependencies: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    kind: str = "采集"
    boundary: str = ""
    related: tuple[str, ...] = ()
    optional_fields: str = ""


@dataclass(frozen=True)
class CheckEvidence:
    criterion: str
    status: str
    measured: str
    blocking: bool = True
    findings: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "unknown"} or not self.measured.strip():
            raise ValueError("检查证据必须有明确状态与观测结果")
        if type(self.blocking) is not bool or not isinstance(self.findings, tuple) or len(self.findings) > 100:
            raise ValueError('检查适用性或问题样例无效')
        if any(not isinstance(item, dict) or not isinstance(item.get('message'), str)
               or not item['message'].strip() or any(not isinstance(value, str) for value in item.values())
               for item in self.findings):
            raise ValueError('问题样例必须包含明确文字说明和字符串定位信息')


@dataclass(frozen=True)
class PreparationContribution:
    requirement: str
    capability: str
    source: str
    project_id: str
    job_key: str
    dataset: str
    collector: str
    source_tests: tuple[str, ...]
    archive_tests: tuple[str, ...]
    method: str = "preparation_check"
    scoped: bool = False
    cache_revision: int = 1
    response_group: str = ''
    analysis_quality_limits: bool = False


@dataclass(frozen=True)
class ComputationContribution:
    """A read-only derived query; it has no collector or archive dataset."""
    requirement: str
    capability: str
    source: str
    project_id: str
    rule_tests: tuple[str, ...]
    integration_tests: tuple[str, ...]
    output_version: str
    page_id: str = ''
    execute_method: str = 'calculate'
    method: str = 'preparation_check'
    scoped: bool = True
    cache_revision: int = 1
