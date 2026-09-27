"""Internal, allowlisted dataset contributions consumed by the archive catalog."""

from dataclasses import dataclass, field
from types import ModuleType

from empire.core.identity import safe_project_id


@dataclass(frozen=True)
class DatasetContribution:
    mapping: ModuleType | object
    mode: str
    projects: dict[str, str] = field(default_factory=dict)
    stale_outcome: str = "complete"

    def __post_init__(self):
        datasets = getattr(self.mapping, "DATASETS", None)
        namespace = getattr(self.mapping, "FINGERPRINT_NAMESPACE", None)
        if (not isinstance(datasets, set) or not datasets
                or not all(isinstance(value, str) and value for value in datasets)):
            raise ValueError("数据贡献必须声明非空 DATASETS")
        if self.mode not in ("aggregate", "incremental"):
            raise ValueError("数据贡献归档模式必须是 aggregate 或 incremental")
        if not isinstance(namespace, str) or not namespace:
            raise ValueError("数据贡献必须声明 fingerprint namespace")
        if self.mode == "aggregate" and not callable(getattr(self.mapping, "assemble", None)):
            raise ValueError("聚合数据贡献必须提供 assemble")
        if (self.mode == "aggregate"
                and not callable(getattr(self.mapping, "aggregate_result_keys", None))):
            raise ValueError("聚合数据贡献必须声明运行结果键")
        if self.stale_outcome not in ("complete", "superseded"):
            raise ValueError("过时数据结果状态无效")
        for job_key, project_id in self.projects.items():
            if safe_project_id(job_key) != job_key or safe_project_id(project_id) != project_id:
                raise ValueError("数据贡献的任务和项目 ID 无效")

    @property
    def datasets(self):
        return self.mapping.DATASETS

    @property
    def namespace(self):
        return self.mapping.FINGERPRINT_NAMESPACE

    @property
    def version(self):
        return self.mapping.FINGERPRINT_VERSION

    def project_id(self, envelope):
        return self.projects.get(envelope.job_key, safe_project_id(envelope.job_key or envelope.source))

    def is_complete(self, envelope):
        predicate = getattr(self.mapping, "is_complete", None)
        return predicate(envelope) if predicate else envelope.dataset.endswith(".complete")
