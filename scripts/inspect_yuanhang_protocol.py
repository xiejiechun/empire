"""Read-only P0 inventory of installed Yuanhang managed protocol metadata.

Never loads/executes vendor assemblies, reads user configuration, or connects to
the source. An inventory is not a successful source request or collection proof.
Install optional dependencies from requirements-yuanhang-research.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ASSEMBLIES = (
    "Hevo.Api.Quotes.dll", "Hevo.Core.Interfaces.dll",
    "Hevo.DataModel.Business.dll", "Hevo.Gms.Wrapper.dll",
)
METHODS = {
    "RequestCandleDataAsync", "RequestCandleV1", "QueryFinanceDataAsync",
    "RequestSecurityInfoListV2", "RequestInfoServerFileV2",
    "RequestDataV1Async", "RequestDataV2Async", "RequestDataV3Async",
    "RequestDataV4Async", "SetProxy", "SetAuthInfo", "CreateSession",
    "ConnectSessionAsync", "DoRequestAsync", "ReleaseGmsSessionSdk",
}
TYPES = {
    "ICandleParameterFactory", "ICandleQuoteParameters", "IBaseTimeRange",
    "IQueryFinanceDataProvider", "IFieldsHolder", "IAuthHandler", "IProxyHandler",
    "ProxySetting", "ProxyType", "ServerInfoModel", "GmsSetting",
}
FIELDS = {
    "prev_close", "open", "high", "low", "close", "transaction_volume",
    "transaction_volume_shou", "transaction_amount", "turnover_rate",
    "real_turnover_rate", "outstanding_shares", "total_capital_stock",
    "FLOAT_CAP", "CAPITAL", "TOTALCAPITAL", "FinanceData",
}


def constant(instruction):
    opcode = str(instruction.opcode)
    if opcode in ("ldc.i4", "ldc.i4.s"):
        return int(instruction.operand)
    if opcode == "ldc.i4.m1":
        return -1
    if opcode.startswith("ldc.i4.") and opcode[-1].isdigit():
        return int(opcode[-1])
    return None


def initializers(pe, definition, body_reader) -> dict:
    """Accept only two literal constants -> factory call -> static assignment.

    Do not execute code or guess values for a different initializer shape.
    """
    result = {}
    for method in definition.MethodList:
        if str(method.row.Name) != ".cctor" or not method.row.Rva:
            continue
        instructions = body_reader(method.row.Rva, 100000).instructions
        for index, instruction in enumerate(instructions):
            if str(instruction.opcode) != "stsfld" or index < 3:
                continue
            a, b, call = instructions[index - 3:index]
            values = [constant(a), constant(b)]
            if None in values or str(call.opcode) != "call":
                continue
            token = call.operand.value
            if token >> 24 != 10:
                continue
            member = pe.net.mdtables.MemberRef.rows[(token & 0xFFFFFF) - 1]
            owner = member.Class.row
            result[instruction.operand.value] = dict(
                factory=f"{getattr(owner, 'TypeNamespace', '')}."
                        f"{getattr(owner, 'TypeName', '')}::{member.Name}",
                factory_integer_arguments=values,
            )
    return result


def inventory(path: Path) -> dict:
    import dnfile
    from dncil.cil.body import CilMethodBody
    from dncil.cil.body.reader import CilMethodBodyReaderBytes

    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError(f"Missing or oversized expected assembly: {path.name}")
    raw = path.read_bytes()
    pe = dnfile.dnPE(data=raw)
    try:
        if pe.net is None or pe.net.mdtables.TypeDef is None:
            raise ValueError(f"Not a managed assembly: {path.name}")
        rows, field_getters = [], []
        def read_body(rva, size):
            return CilMethodBody(CilMethodBodyReaderBytes(pe.get_data(rva, size)))

        for definition in pe.net.mdtables.TypeDef:
            typename = str(definition.TypeName)
            full_name = f"{definition.TypeNamespace}.{typename}"
            values = initializers(pe, definition, read_body) if typename == "QuoteFields" else {}
            for index in definition.MethodList:
                method = index.row
                method_name = str(method.Name)
                if method_name in METHODS or typename in TYPES:
                    rows.append(dict(
                        type=full_name, method=method_name,
                        token=f"0x{0x06000000 + index.row_index:08x}",
                        parameters=[dict(position=x.row.Sequence, name=str(x.row.Name))
                                    for x in method.ParamList],
                        signature_hex=method.Signature.value.hex(),
                    ))
                if typename != "QuoteFields" or method_name.removeprefix("get_") not in FIELDS:
                    continue
                item = dict(field=method_name, literals=[], integer_operands=[])
                # Keep bounded getter evidence only, never dump arbitrary strings
                # or authentication/session material from other methods.
                if method.Rva:
                    body = read_body(method.Rva, 4096)
                    for instruction in body.instructions:
                        opcode, operand = str(instruction.opcode), instruction.operand
                        if opcode == "ldstr":
                            value = pe.net.user_strings.get(operand.value & 0xFFFFFF).value
                            if len(value) <= 100:
                                item["literals"].append(value)
                        elif opcode.startswith("ldc.i4"):
                            item["integer_operands"].append(dict(opcode=opcode, operand=operand))
                        elif opcode == "ldsfld" and operand.value in values:
                            item["static_initializer"] = values[operand.value]
                field_getters.append(item)
        assembly = pe.net.mdtables.Assembly.rows[0]
        version = ".".join(str(getattr(assembly, key)) for key in
                           ("MajorVersion", "MinorVersion", "BuildNumber", "RevisionNumber"))
        return dict(file=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                    assembly_version=version, methods=rows, quote_field_getters=field_getters)
    finally:
        pe.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a fresh evidence path")
    reports = [inventory(args.client_bin / name) for name in ASSEMBLIES]
    found = {m["method"] for report in reports for m in report["methods"]}
    required = {"RequestCandleV1", "RequestCandleDataAsync", "SetProxy", "DoRequestAsync"}
    if not required <= found:
        raise ValueError("Installed client contract differs: required methods missing")
    report = dict(
        schema=1, observed_at=datetime.now(UTC).isoformat(),
        verification="offline_metadata_only", source_request_verified=False,
        history_coverage_verified=False, proxy_acceptance_verified=False,
        production_mutated=False, assemblies=reports,
        unresolved=["wire handshake/session", "daily paging and units",
                    "corporate-action request and identity", "historical float semantics",
                    "shared transport/proxy integration", "end-to-end archive verification"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"PASS offline inventory: {len(reports)} assemblies; no source request performed")


if __name__ == "__main__":
    main()
