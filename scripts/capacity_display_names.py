"""Reuse immutable capacity evidence only for a proved task-label suffix removal."""
import ast
import hashlib
import json


def equivalent(before, after):
    old, new = ast.parse(before), ast.parse(after)
    def calls(tree):
        return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == 'TaskContribution']
    previous, current = calls(old), calls(new)
    if len(previous) != len(current):
        return False
    changed = False
    for a, b in zip(previous, current, strict=True):
        if len(a.args) < 2 or len(b.args) < 2:
            return False
        left, right = a.args[1], b.args[1]
        if ast.dump(left) == ast.dump(right):
            continue
        # Only the existing pure item[0] + platform suffix expression is
        # removable. Calls, attributes, schedules and all other AST stay exact.
        if not (isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add)
                and isinstance(left.right, ast.Constant)
                and left.right.value in ('（通达信）', '（同花顺）', '（东方财富）', '（开盘啦）')
                and ast.dump(left.left) == ast.dump(ast.parse('item[0]', mode='eval').body)
                and ast.dump(right) == ast.dump(left.left)):
            return False
        a.args[1] = b.args[1] = ast.Constant(value='reviewed task display name')
        changed = True
    return changed and ast.dump(old) == ast.dump(new)


def preserved_binding(root, resource, checksum):
    proof = root / 'docs/capacity-display-names.json'
    if not proof.is_file():
        return False
    data = json.loads(proof.read_text('utf8'))
    if data.get('schema') != 1 or resource not in data.get('bindings', {}):
        return False
    item = data['bindings'][resource]
    paths = [item['before'], item['design'], *item['tests'], resource]
    if not item['tests'] or any(not (root / p).resolve().is_relative_to(root.resolve())
                               or not (root / p).is_file() for p in paths):
        raise ValueError('Display-name evidence proof needs owned baseline/design/tests')
    baseline = (root / item['before']).read_bytes()
    return (hashlib.sha256(baseline).hexdigest() == checksum
            and equivalent(baseline.decode('utf8'), (root / resource).read_text('utf8')))
