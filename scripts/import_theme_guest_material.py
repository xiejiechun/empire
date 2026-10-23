"""Explicit import of locally prepared guest material, never print its values."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from empire.core.config import default_config_path  # noqa: E402
from empire.features.themes.guest_material import import_material  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=default_config_path())
    parser.add_argument('--stdin', action='store_true', required=True,
                        help='Read local material JSON from standard input; never an account session')
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(500001)
        if len(raw) > 500000:
            raise ValueError('材料超限')
        import_material(args.config, json.loads(raw))
    except Exception:
        print('FAIL: 材料导入失败；检查当前用户、材料契约及配置已有内容。未输出凭据。', file=sys.stderr)
        return 1
    print('PASS: 游客协议材料已由当前Windows用户保护并写入指定程序配置。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
