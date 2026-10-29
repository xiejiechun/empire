"""Durable node-code bindings. A local profile is not a source-issued guest account."""
import base64
import json
import re
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from empire.sources.yuanhang_auth import ClientDevice
from empire.sources.yuanhang_identity import GuestIdentity
from empire.sources.yuanhang_recipe import creation_recipe, timestamp, validate_recipe

KIND, KEY = 'yuanhang', 'guest-profiles'
MAX_NODES, MAX_BYTES = 1000, 4 * 1024 * 1024


def node_code(code):
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', code):
        raise ValueError('远航身份绑定需要有效的代理设备code')
    return code


@dataclass(frozen=True)
class NodeProfile:
    code: str
    profile_id: str
    identity: GuestIdentity | None = field(default=None, repr=False)
    device: ClientDevice | None = field(default=None, repr=False)
    registration: str = 'unrequested'
    creation: dict = field(default_factory=dict, repr=False)
    rejection_code: int | None = None

    @property
    def provisioned(self):
        return self.identity is not None and self.device is not None


class ProfileRegistry:
    def __init__(self, settings, protection):
        self.settings, self.protection = settings, protection

    def _context(self, code, profile_id):
        return f'empire:yuanhang:v1:{self.settings.namespace}:{code}:{profile_id}'.encode('utf8')

    def _read(self, data):
        if data is None:
            return {}
        try:
            if (set(data) != {'schema', 'profiles'} or data['schema'] != 2
                    or not isinstance(data['profiles'], dict) or len(data['profiles']) > MAX_NODES
                    or len(json.dumps(data).encode()) > MAX_BYTES):
                raise ValueError
            result, accounts, ids, devices = {}, set(), set(), set()
            for code, value in data['profiles'].items():
                node_code(code)
                if (not {'profile_id', 'registration', 'creation'} <= value.keys()
                        or set(value) - {'profile_id', 'registration', 'protected', 'rejection_code', 'creation'}):
                    raise ValueError
                ident = value['profile_id']
                if str(UUID(ident)) != ident or ident in ids:
                    raise ValueError
                ids.add(ident)
                device = validate_recipe(value['creation'], ident)
                if device.mac in devices:
                    raise ValueError
                devices.add(device.mac)
                state = value['registration']
                if (state not in {'unrequested', 'requested', 'rejected', 'unknown', 'ready'}
                        or (state == 'ready') != ('protected' in value)
                        or ('rejection_code' in value and
                            (state != 'rejected' or type(value['rejection_code']) is not int))):
                    raise ValueError
                identity = None
                if 'protected' in value:
                    raw = base64.b64decode(value['protected'], validate=True)
                    payload = json.loads(self.protection.open(raw, self._context(code, ident)))
                    if set(payload) != {'account', 'password'}:
                        raise ValueError
                    account, password = payload['account'], payload['password']
                    if (not isinstance(account, str) or not re.fullmatch(r'thsguest_[A-Za-z0-9_.-]{1,100}', account)
                            or not isinstance(password, str) or not 1 <= len(password) <= 512
                            or any(ord(c) < 33 or ord(c) > 126 for c in password) or account in accounts):
                        raise ValueError
                    accounts.add(account)
                    identity = GuestIdentity(account, password)
                result[code] = NodeProfile(code, ident, identity, device, state,
                                           value['creation'], value.get('rejection_code'))
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('远航节点身份配置损坏、版本待迁移或无法解密；保留原配置，不重新分配') from None

    async def load(self):
        values = await self.settings.load(KIND)
        if set(values) - {KEY}:
            raise ValueError('远航身份配置存在未知条目')
        return self._read(values.get(KEY))

    async def ensure(self, codes):
        """Persist once; removed/offline nodes are intentionally retained."""
        requested = {node_code(code) for code in codes}
        if len(requested) > MAX_NODES:
            raise ValueError('远航节点身份数量超过1000')

        def update(old):
            current = self._read(old)
            values = dict((old or {}).get('profiles', {}))
            if len(current.keys() | requested) > MAX_NODES:
                raise ValueError('远航保留节点身份数量超过1000')
            for code in sorted(requested - current.keys()):
                ident = str(uuid4())
                values[code] = {'profile_id': ident, 'registration': 'unrequested',
                                'creation': creation_recipe(ident)}
            return {'schema': 2, 'profiles': values}

        saved = await self.settings.mutate(KIND, KEY, update)
        return self._read(saved)

    async def bind(self, code, identity: GuestIdentity, device: ClientDevice):
        """Bind explicitly supplied normal credentials; never copy a default account."""
        node_code(code)
        if not isinstance(identity, GuestIdentity) or not isinstance(device, ClientDevice):
            raise ValueError('绑定需要明确游客凭据与客户端身份')

        def update(old):
            profiles = self._read(old)
            if code not in profiles:
                raise ValueError('请先建立该节点的持久身份槽位')
            profile = profiles[code]
            if device != profile.device:
                raise ValueError('节点逻辑客户端标识不可替换为其他设备信息')
            if profile.provisioned:
                if profile.identity == identity and profile.device == device:
                    return old
                raise ValueError('节点已有固定身份，不能隐式替换')
            if any(p.identity and p.identity.account == identity.account for p in profiles.values()):
                raise ValueError('一个游客账号不能绑定多个节点')
            payload = json.dumps(dict(account=identity.account, password=identity.password), sort_keys=True).encode()
            sealed = self.protection.seal(payload, self._context(code, profile.profile_id))
            values = dict(old['profiles'])
            values[code] = {**values[code], 'registration': 'ready',
                            'protected': base64.b64encode(sealed).decode('ascii')}
            values[code].pop('rejection_code', None)
            result = {'schema': 2, 'profiles': values}
            self._read(result)
            return result

        saved = await self.settings.mutate(KIND, KEY, update)
        return self._read(saved)[code]

    async def transition(self, code, expected, state, *, rejection_code=None):
        if (expected, state) not in {('unrequested', 'requested'), ('requested', 'rejected'),
                                    ('requested', 'unknown')}:
            raise ValueError('不允许重置或轮换游客申请状态')

        def update(old):
            profiles = self._read(old)
            if code not in profiles or profiles[code].registration != expected:
                raise ValueError('节点身份申请状态已变化，不重复申请')
            values = dict(old['profiles'])
            values[code] = {**values[code], 'registration': state}
            if state == 'requested':
                values[code]['creation'] = {**values[code]['creation'], 'requested_at': timestamp()}
            if rejection_code is not None:
                values[code]['rejection_code'] = rejection_code
            result = {'schema': 2, 'profiles': values}
            self._read(result)
            return result

        saved = await self.settings.mutate(KIND, KEY, update)
        return self._read(saved)[code]
