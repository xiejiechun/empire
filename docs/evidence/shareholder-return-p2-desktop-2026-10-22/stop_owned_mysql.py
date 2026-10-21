"""Normal SHUTDOWN of the audited, now-unused private instance only."""
import json
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError
from empire.plugins.infra.mysql_store import make_engine

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'private-mysql-close.json'
assert not OUT.exists()
settings=json.loads((ROOT/'build/architecture-evolution-20261019/mysql-settings.json').read_text('utf8'))
engine=make_engine(dict(settings,database='mysql'),pool_size=1)
report=dict(at=datetime.now(UTC).isoformat(),operation='normal SQL SHUTDOWN; no process termination',result='not_closed')
try:
    with engine.connect() as conn:
        row=dict(conn.exec_driver_sql('SELECT @@server_uuid AS server_uuid,@@port AS port,@@datadir AS datadir,CONNECTION_ID() AS connection_id').mappings().one())
        assert row['server_uuid']=='a3e8a5eb-cb64-11f1-8ddf-380525361d4e'
        assert row['port']==13348
        assert Path(row['datadir']).resolve()==(ROOT/'build/architecture-evolution-20261019/mysql-data').resolve()
        databases=conn.exec_driver_sql('SHOW DATABASES').scalars().all()
        assert set(databases)=={'information_schema','mysql','performance_schema','sys'}
        clients=list(conn.exec_driver_sql('SHOW FULL PROCESSLIST').mappings())
        assert all(c['Id']==row['connection_id'] or c['User']=='event_scheduler' for c in clients)
        report.update(identity=row,databases=databases,other_clients=0)
        conn.commit()
        try:
            conn.exec_driver_sql('SHUTDOWN')
        except OperationalError as exc:
            assert exc.orig.args[0] in (2006,2013)
        report['normal_shutdown_requested']=True
        conn.invalidate()
finally:
    engine.dispose()
    if report.get('normal_shutdown_requested'):
        for _ in range(25):
            try:
                with socket.create_connection(('127.0.0.1',13348),timeout=.2):
                    reachable=True
            except OSError:
                reachable=False
            if not reachable:
                report['result']='closed'
                break
            time.sleep(.2)
    with OUT.open('x',encoding='utf8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
assert report['result']=='closed'
print('Owned13348 normal shutdown verified; four system databases; no other clients.')
