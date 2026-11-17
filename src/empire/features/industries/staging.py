"""Short-lived normalized recovery material, never a publication proof."""
import copy
import json
from datetime import timedelta

from empire.features.industries.dataset import digest, validate


class IndustryStage:
    def __init__(self):
        self.clear()

    def clear(self):
        self.started = None
        self.scope = ''
        self.units = {}
        self.size = 0

    def begin(self, catalog, now, *, fresh=False):
        scope = digest(catalog)
        if (fresh or self.started is None or self.scope != scope
                or not timedelta(0) <= now - self.started <= timedelta(minutes=30)):
            self.clear()
            self.started, self.scope = now, scope
        return self.started

    def get(self, code):
        return copy.deepcopy(self.units.get(code))

    def put(self, industry):
        validate([industry])
        body = json.dumps(industry, ensure_ascii=False, separators=(',', ':')).encode()
        if industry['code'] in self.units:
            raise ValueError('行业恢复单元重复')
        if len(self.units) >= 500 or self.size + len(body) > 2 * 1024 * 1024:
            raise ValueError('行业恢复材料超过2MiB边界')
        self.units[industry['code']] = copy.deepcopy(industry['members'])
        self.size += len(body)
