"""Explicit schema1→2 identity configuration migration. No source requests or DDL."""
import argparse
import copy
import json

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.settings import SettingsStore
from empire.sources.yuanhang_profiles import KEY, KIND, ProfileRegistry
from empire.sources.yuanhang_recipe import creation_recipe


def upgrade(value, registry):
    if value is None or value.get('schema') == 2:
        registry._read(value)
        return value
    if set(value) != {'schema', 'profiles'} or value['schema'] != 1:
        raise ValueError('Unsupported legacy identity configuration')
    result = copy.deepcopy(value)
    result['schema'] = 2
    for code, profile in result['profiles'].items():
        if set(profile) - {'profile_id', 'registration', 'protected', 'rejection_code'}:
            raise ValueError('Unknown legacy profile fields; migration refused')
        profile['creation'] = creation_recipe(profile['profile_id'], legacy=True)
    registry._read(result)  # Includes all original account uniqueness and DPAPI checks.
    restored = {'schema': 1, 'profiles': {code: {k: v for k, v in p.items() if k != 'creation'}
                                        for code, p in result['profiles'].items()}}
    if restored != value:
        raise ValueError('Identity preservation verification failed')
    return result


def migrate_database(engine, namespace, protection, *, apply=False):
    store = SettingsStore(None, namespace)
    registry = ProfileRegistry(store, protection)
    params = dict(namespace=namespace, kind=KIND, key=KEY)
    query = text('SELECT payload FROM app_setting WHERE namespace=:namespace AND kind=:kind '
                 'AND setting_key=:key FOR UPDATE')
    with engine.begin() as conn:
        old = conn.execute(query, params).scalar_one_or_none()
        old = json.loads(old) if isinstance(old, str) else old
        new = upgrade(old, registry)
        changed = new != old
        if apply and changed:
            store.save_in_transaction(conn, KIND, KEY, new)
            saved = conn.execute(query, params).scalar_one()
            if (json.loads(saved) if isinstance(saved, str) else saved) != new:
                raise ValueError('Migration readback mismatch')
        return dict(applied=apply, changed=changed, profiles=len((new or {}).get('profiles', {})),
                    identities_preserved=True, source_requests=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    lock = engine = None
    try:
        cfg = load_config(args.config)
        lock = acquire_instance_lock()
        engine = make_engine(cfg['mysql'])
        print(json.dumps(migrate_database(engine, cfg['redis']['namespace'], WindowsProtection(),
                                          apply=args.apply)))
    except Exception as exc:
        raise SystemExit('Identity migration failed: ' + type(exc).__name__ + '; original configuration retained') from None
    finally:
        if engine is not None:
            engine.dispose()
        if lock is not None:
            lock.unlock()


if __name__ == '__main__':
    main()
