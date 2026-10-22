import json, socket, subprocess, time
from pathlib import Path
from datetime import UTC, datetime
from empire.plugins.infra.mysql_store import make_engine
root=Path(__file__).resolve().parents[2]
out=Path(__file__).parent
data=(root/'build/architecture-evolution-20261019/mysql-data').resolve()
assert data.is_relative_to(root/'build')
assert 'a3e8a5eb-cb64-11f1-8ddf-380525361d4e' in (data/'auto.cnf').read_text()
with socket.socket() as sock:
    assert sock.connect_ex(('127.0.0.1',13348)) != 0, 'Port already owned; investigate, do not replace'
args=['E:/mysql/empire/server/bin/mysqld.exe','--no-defaults',f'--datadir={data}',
      '--port=13348','--bind-address=127.0.0.1','--mysqlx=0','--skip-log-bin',
      '--innodb-buffer-pool-size=64M','--innodb-flush-log-at-trx-commit=2',
      '--general-log=0','--slow-query-log=0',f'--log-error={out / "private-mysql.log"}']
proc=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
(out/'private-mysql-pid.txt').write_text(str(proc.pid))
for _ in range(40):
    assert proc.poll() is None, 'Owned server exited; inspect its local log'
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',13348)) == 0: break
    time.sleep(.25)
settings=json.loads((root/'build/architecture-evolution-20261019/mysql-settings.json').read_text())
engine=make_engine(dict(settings,database='mysql'),pool_size=1)
try:
    with engine.connect() as conn:
        identity=dict(conn.exec_driver_sql('SELECT @@server_uuid AS server_uuid,@@port AS port,@@datadir AS datadir,CONNECTION_ID() AS connection_id').mappings().one())
        assert identity['server_uuid']=='a3e8a5eb-cb64-11f1-8ddf-380525361d4e' and identity['port']==13348
        assert Path(identity['datadir']).resolve()==data
        databases=conn.exec_driver_sql('SHOW DATABASES').scalars().all()
        assert set(databases)=={'mysql','sys','performance_schema','information_schema'}
        clients=conn.exec_driver_sql('SHOW PROCESSLIST').mappings().all()
        assert all(c['Id']==identity['connection_id'] or c['User']=='event_scheduler' for c in clients)
        report=dict(at=datetime.now(UTC).isoformat(),pid=proc.pid,identity=identity,databases=databases,other_clients=0)
        (out/'private-mysql-start.json').write_text(json.dumps(report,indent=2))
        print(report)
finally: engine.dispose()
