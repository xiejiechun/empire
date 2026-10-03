"""Explicitly copy a selected old configuration into the application directory."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from empire.core.config import default_config_path, load_config


def migrate(source: Path, destination: Path) -> str:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Legacy configuration does not exist: {source}")
    payload = source.read_bytes()
    load_config(source)
    if destination.is_file():
        if destination.read_bytes() == payload:
            return "already-current"
        raise RuntimeError(
            f"Destination already contains different configuration; refusing to overwrite: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".config-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic, non-replacing publication; the temporary file is on the same volume.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return "migrated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=default_config_path())
    args = parser.parse_args()
    status = migrate(args.source, args.destination)
    print(f"PASS program configuration {status}: {args.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
