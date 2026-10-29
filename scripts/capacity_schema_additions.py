"""Prove old measured schemas unchanged when reviewed new tables are appended."""

import hashlib
import json
import re


def preserved_binding(root, resource, checksum):
    allowed = {"sql/schema.sql", "sql/schema-contract.json", "sql/business-schema.json"}
    if resource not in allowed:
        return False
    path = root / "docs/capacity-schema-additions.json"
    if not path.is_file():
        return False
    proof = json.loads(path.read_text("utf8"))
    if proof.get("schema") != 1 or set(proof.get("baselines", {})) != allowed:
        return False
    for name in proof["baselines"].values():
        if not (root / name).resolve().is_relative_to(root.resolve()):
            raise ValueError("容量结构基线不能越出项目")
    original = root / proof["baselines"][resource]
    if not original.resolve().is_relative_to(root.resolve()):
        raise ValueError("容量结构基线不能越出项目")
    if hashlib.sha256(original.read_bytes()).hexdigest() != checksum:
        return False
    for filename in [proof["design"], *proof["tests"]]:
        target = (root / filename).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError("容量结构追加证明缺少设计或测试")
    tables, datasets = set(proof["added_tables"]), set(proof["added_datasets"])
    if not tables or not datasets:
        raise ValueError("容量结构追加证明不能为空")
    old = {key: (root / name).read_text("utf8") for key, name in proof["baselines"].items()}
    current = {key: (root / key).read_text("utf8") for key in old}

    def ddl(value):
        return {
            m[1]: m[0]
            for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\([\s\S]*?;", value)
        }

    before, after = ddl(old["sql/schema.sql"]), ddl(current["sql/schema.sql"])
    if set(after) - set(before) != tables or any(after.get(t) != sql for t, sql in before.items()):
        raise ValueError("既有容量DDL已改变，必须重新测量")
    previous = json.loads(old["sql/schema-contract.json"])
    actual = json.loads(current["sql/schema-contract.json"])
    if set(actual["tables"]) - set(previous["tables"]) != tables:
        raise ValueError("结构契约追加表集合不同")
    actual["tables"] = {k: v for k, v in actual["tables"].items() if k not in tables}
    actual["schema_sha256"] = previous["schema_sha256"]
    if actual != previous:
        raise ValueError("既有容量字段、索引或约束改变，必须重新测量")
    previous = json.loads(old["sql/business-schema.json"])
    actual = json.loads(current["sql/business-schema.json"])
    for group in ("fixed_sources", "primary_keys"):
        for table in tables:
            actual[group].pop(table)
    actual["tables"] = [t for t in actual["tables"] if t not in tables]
    for group in ("dataset_tables", "dataset_table_groups"):
        if set(actual[group]) - set(previous[group]) != datasets:
            raise ValueError("容量数据集追加集合不同")
        for dataset in datasets:
            actual[group].pop(dataset)
    if actual != previous:
        raise ValueError("既有容量业务归属改变，必须重新测量")
    return True
