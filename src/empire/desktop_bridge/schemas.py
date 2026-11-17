"""Renderer input is untrusted; no arbitrary capability, method or plugin access."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Request(Model):
    id: Identifier
    operation: str = Field(min_length=1, max_length=64)
    session_id: str = Field(default='', max_length=64)
    operation_id: Identifier | None = None
    params: dict = Field(default_factory=dict)


class Empty(Model):
    pass


class ReviewMarket(Model):
    date: str = Field(pattern=r'^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$')

    @field_validator('date')
    @classmethod
    def valid_date(cls, value):
        from datetime import date
        date.fromisoformat(value)
        return value


class ObservationMetric(Model):
    market: Literal['99', '3', '2', '4'] | None = None
    mode: Literal['value', 'change', 'sum'] = 'value'
    days: int = Field(default=5, ge=1, le=60)
    window: int = Field(default=30, ge=1, le=60)
    top: int = Field(default=5, ge=1, le=100)


class Observation(Model):
    month: str = Field(pattern=r'^(19[9][1-9]|20[0-9]{2})-(0[1-9]|1[0-2])$')
    index: str = Field(pattern=r'^[0-9A-Z]{6}$')
    market: Literal['99', '3', '2', '4'] = '99'
    settings: dict[str, ObservationMetric] = Field(default_factory=dict, max_length=26)
    include_top: bool = False
    include_turnover: bool = False
    include_fx: list[Annotated[str, Field(pattern=r'^fx_(USDIND|USDCNY|USDCNH|XAUUSD|EURUSD|GBPUSD|USDCAD|USDCHF|USDHKD|AUDUSD|USDJPY|USDSGD)$')]] = Field(default_factory=list, max_length=12)


class LiveBasis(Model):
    mode: Literal['value', 'change', 'sum']
    days: int = Field(ge=1, le=60)
    ready: bool
    total: str = Field(max_length=80, pattern=r'^[0-9]{1,30}(\.[0-9]{1,50})?$')


class ObservationLive(Model):
    date: str = Field(pattern=r'^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$')
    basis: dict[Annotated[str, Field(pattern=r'^fx_(USDIND|USDCNY|USDCNH|XAUUSD|EURUSD|GBPUSD|USDCAD|USDCHF|USDHKD|AUDUSD|USDJPY|USDSGD)$')], LiveBasis] = Field(max_length=12)


class Page(Model):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=100)


class Tasks(Page):
    query: str = Field(default='', max_length=100)
    source: str = Field(default='', max_length=100)
    category: str = Field(default='', max_length=100)
    status: str = Field(default='', max_length=40)
    archived: bool = False


class Task(Model):
    ident: Identifier


class PreviewOrder(Model):
    field: Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')]
    direction: Literal['asc', 'desc']


class Preview(Task):
    view: Identifier
    filters: dict[Annotated[str, Field(max_length=20)], Annotated[str, Field(max_length=100)]] = Field(default_factory=dict, max_length=8)
    cursor: str = Field(default='null', max_length=262144)
    order: PreviewOrder | None = None


class Run(Task):
    fresh: bool = False


class Policy(Model):
    enabled: bool
    mode: Literal['manual', 'interval', 'daily']
    interval_seconds: int = Field(ge=1, le=2592000)
    daily_time: str = Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    request_retries: int = Field(ge=0, le=100)
    use_proxy: bool
    proxy_fallback: bool


class SavePolicy(Task):
    policy: Policy


class Archive(Task):
    archived: bool


class Batch(Model):
    operation: Literal['start', 'stop']
    identifiers: list[Identifier] = Field(min_length=1, max_length=100)


class Records(Page):
    kind: Literal['collection', 'archives', 'errors'] = 'collection'
    project: str = Field(default='', max_length=100)


class ErrorDetail(Task):
    record_id: str = Field(min_length=1, max_length=256)


class ClearErrors(Task):
    record_ids: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(min_length=1, max_length=300)


class Events(Page):
    ident: Identifier
    run_id: str = Field(default='', max_length=100)
    unlinked: bool = False
    stage: Literal['', 'collection', 'archives', 'errors'] = ''


class SiteValues(Model):
    scaling_mode: Literal['auto', 'fixed']
    proxy_interval_ms: int = Field(ge=100, le=60000)
    min_interval_ms: int = Field(ge=100, le=60000)
    total_interval_ms: int = Field(ge=100, le=60000)
    max_concurrency: int = Field(ge=0, le=1024)
    max_rps: int = Field(ge=0, le=100)


class SiteSave(Model):
    name: Identifier
    values: SiteValues


class ResourceSave(Model):
    values: dict[str, int]


class Identity(Page):
    platform: Identifier


class IdentityCommand(Model):
    platform: Identifier
    action: Literal['start', 'stop']


class Cancel(Model):
    request_id: Identifier


READS = {
    'review.market': ReviewMarket,
    'observation.catalog': Empty, 'observation.read': Observation, 'observation.live': ObservationLive,
    'preview.catalog': Task, 'preview.read': Preview,
    'session.handshake': Empty, 'health.read': Empty, 'tasks.list': Tasks, 'run.events': Events,
    'task.read': Task, 'collection.rules.read': Task, 'records.list': Records,
    'error.read': ErrorDetail, 'sites.list': Page, 'exits.read': Empty,
    'resources.read': Empty,
    'identities.catalog': Empty, 'identities.read': Identity,
}
WRITES = {
    'collection.policy.save': SavePolicy, 'collection.run': Run,
    'collection.pause': Task, 'collection.batch': Batch, 'collection.archive': Archive,
    'errors.clear': ClearErrors, 'sites.save': SiteSave,
    'resources.save': ResourceSave, 'identity.service': IdentityCommand,
}
