"""Static, ordered business contributions; runtime lifetimes remain plugins."""
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Generic, TypeVar

from empire.contracts.confirmation import ConfirmationContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.plugin import Plugin
from empire.contracts.task import TaskContribution
from empire.core.identity import safe_project_id

T = TypeVar('T')


@dataclass(frozen=True)
class OrderedContribution(Generic[T]):
    ordinal: int
    value: T

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError('贡献顺序须为正整数')


def positioned(ordinals: tuple[int, ...], values: Iterable[T]) -> tuple[OrderedContribution[T], ...]:
    """Fixed slots deliberately fail if a parameterized series changes size."""
    return tuple(OrderedContribution(order, value) for order, value in zip(ordinals, values, strict=True))


@dataclass(frozen=True)
class MaintenancePublisher:
    project_id: str
    job_key: str
    entrypoint: str

    def __post_init__(self) -> None:
        if (not self.project_id or not self.job_key
                or safe_project_id(self.project_id) != self.project_id
                or safe_project_id(self.job_key) != self.job_key):
            raise ValueError('维护发布者须声明精确项目与 job 身份')
        path = PurePosixPath(self.entrypoint)
        if (not self.entrypoint or not path.parts or '\\' in self.entrypoint or path.is_absolute()
                or '..' in path.parts or path.parts[0] != 'scripts' or path.suffix != '.py'
                or path.as_posix() != self.entrypoint):
            raise ValueError('维护发布者入口须为 scripts 下的相对 Python 文件')


@dataclass(frozen=True)
class FeatureBundle:
    id: str
    plugins: tuple[OrderedContribution[Plugin], ...] = ()
    tasks: tuple[OrderedContribution[TaskContribution], ...] = ()
    datasets: tuple[OrderedContribution[DatasetContribution], ...] = ()
    confirmations: tuple[ConfirmationContribution, ...] = ()
    maintenance_publishers: tuple[MaintenancePublisher, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or safe_project_id(self.id) != self.id:
            raise ValueError('业务包 ID 无效')


def ordered(contributions: Iterable[tuple[str, OrderedContribution[T]]], domain: str) -> tuple[T, ...]:
    """Order each contribution domain without relying on whitelist order."""
    positions: dict[int, tuple[str, T]] = {}
    for owner, contribution in contributions:
        if contribution.ordinal in positions:
            previous, value = positions[contribution.ordinal]
            def identity(item: object) -> str:
                return str(getattr(getattr(item, 'manifest', None), 'id', None)
                           or getattr(item, 'id', None)
                           or getattr(item, 'namespace', type(item).__name__))
            raise ValueError(f'{domain} 贡献顺序重复 {contribution.ordinal}: '
                             f'{previous}/{identity(value)} / {owner}/{identity(contribution.value)}')
        positions[contribution.ordinal] = (owner, contribution.value)
    return tuple(positions[key][1] for key in sorted(positions))
