"""Owned repurchase capacity lifecycle, preserving the original 50000-row protocol."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from secrets import token_hex

import source_verification as verification
from measure_repurchases import measure
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, read_server_uuid, test_settings
from source_verification import require

from empire.__main__ import acquire_instance_lock
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.features.repurchases.contract import validate
from empire.plugins.infra.sql_lane import settle


class RepurchaseCapacityStorage(PrivateStorage):
    def __init__(self,*args,**kwargs):
        self.explain_sql=set()
        super().__init__(*args,**kwargs)

    def guard(self,conn,cursor,statement,parameters,context,executemany):
        if statement=='ANALYZE TABLE stock_repurchase_plan' and not parameters and not executemany:
            return super().guard(conn,cursor,'SELECT 1',(),context,False)
        if statement in self.explain_sql and not parameters and not executemany:
            return super().guard(conn,cursor,statement[8:],(),context,False)
        return super().guard(conn,cursor,statement,parameters,context,executemany)


def source_proof(path):
    proof=json.loads(Path(path).read_text('utf8'))
    require(proof.get('subject')=='repurchases' and proof.get('mode')=='verification', '来源报告类型错误')
    require(proof.get('source_sha256')==source_digest(project_root()),'来源报告不是当前源码')
    require(proof.get('passed') is True and proof.get('pipeline_verified') is True and proof.get('strict_proxy_verified') is True
            and proof.get('acceptance_complete') is True and not proof.get('errors'), '本轮来源证明未通过')
    require(all(proof.get('cleanup',{}).get(k) is True for k in ('shutdown','sql','redis','sql_lock','connections','instance_lock')),
            '本轮来源资源清理不完整')
    result=proof['results']['eastmoney-repurchases']
    require(result['pending_stream']==0 and result['count']>0 and result['audit']['valid'] is True
            and result['digest']==result['audit']['digest']==result['checkpoint']['digest'], '来源集合与SQL证据不一致')
    validate(proof['first'])
    return proof


async def verify(args):
    output, report = verification.initial_report(args)
    storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, "timeout须为1～7200秒")
        require(
            args.random_count == 0 and args.seed is None and not args.codes,
            "合成容量不能声明随机实采",
        )
        paths = [
            Path(args.pool_config or default_config_path()).resolve(),
            Path(args.test_mysql_settings).resolve(),
        ]
        report["input_files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text("utf-8"))
        require(isinstance(raw, dict), "测试配置须为JSON对象")
        redactor = Redactor(
            [cfg["mysql"].get("password"), cfg["redis"].get("password"), raw.get("password")]
        )
        settings = test_settings(raw)
        proof_path = Path(args.source_proof).resolve()
        proof = source_proof(proof_path)
        report['input_files'][str(proof_path)] = hashlib.sha256(proof_path.read_bytes()).hexdigest()
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg["mysql"])
        report.update(
            subject="repurchases_capacity",
            source_sha256=source_digest(project_root()),
            source_server_uuid=source_uuid,
            acceptance_complete=False,
            sample_30_applicable=False,
            sample_30_reason="原回购50000行SQL容量；不请求来源",
        )
        storage = RepurchaseCapacityStorage(
            settings, cfg["redis"], report["run_id"], token_hex(32), source_uuid
        )
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name + ".ownership.json")
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(
            before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1]))
        )
        report["storage"] = storage.identity()
        report["environment"] = dict(
            storage.conn.exec_driver_sql(
                "SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,"
                "@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,@@sync_binlog AS sync_binlog,@@log_bin AS log_bin"
            )
            .mappings()
            .one()
        )
        await storage.create_redis()
        storage.seed([], [])
        async with asyncio.timeout(args.timeout):
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure, storage, proof["first"])))
        report.update(measured)
        report["source_proof"] = dict(path=str(proof_path), sha256=report["input_files"][str(proof_path)], run_id=proof["run_id"], source_sha256=proof["source_sha256"])
        report["input_files"].update(
            {str(project_root() / p): sha for p, sha in measured["bindings"].items()}
        )
        require(source_digest(project_root()) == report["source_sha256"], "测量期间源码改变")
        require(
            all(measured["measurements"][k] <= v for k, v in measured["limits"].items()),
            "容量超出冻结原预算",
        )
        require(await storage.client.get(storage.owner_key) == storage.owner, "Redis归属变化")
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report["errors"].append(
            dict(stage="capacity", message=redactor.text(exc, 2048), type=type(exc).__name__)
        )
    finally:
        passed = await verification.complete(output, report, redactor, None, storage, lock, False)
    return passed


def main(argv=None):
    parser=verification.parser(__doc__)
    parser.add_argument('--source-proof', required=True, help='本轮当前源码全链路、全代理、清理完成的来源证明')
    parser.set_defaults(random_count=0,timeout=900)
    values=list(sys.argv[1:] if argv is None else argv)
    values=['--test-mysql-settings' if x=='--test-settings' else x for x in values]
    args=parser.parse_args(values)
    _app=QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed=asyncio.run(verification.recover(args) if args.cleanup_only else verify(args))
    print('PASS' if passed else 'FAIL',flush=True)
    return 0 if passed else 1
