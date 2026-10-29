"""Source entry: python -m empire.desktop_bridge [--config explicit-path]."""
import argparse
import sys


def main():
    from PySide6.QtCore import QCoreApplication

    from empire.__main__ import acquire_instance_lock, configure_cli_output, configure_logging
    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import redact
    from empire.core.runtime import Runtime

    from .server import Server

    configure_cli_output()
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    args = parser.parse_args()
    source, destination = sys.stdin.buffer, sys.stdout.buffer
    # Third party print output cannot corrupt the protocol stream.
    sys.stdout = sys.stderr
    cfg, lock, runtime, qt_app = {}, None, None, None
    try:
        cfg = load_config(args.config)
        lock = acquire_instance_lock()
        configure_logging(cfg)
        # Collectors use Qt's local JavaScript engine for request verification.
        # Electron replaces the window, not this process-wide runtime dependency.
        # Keep it alive on the main thread until all worker threads have stopped.
        qt_app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        runtime = Runtime(lambda: build_manager(cfg), cfg)
        runtime.start()
        Server(runtime, source, destination).serve()
        return 0
    except Exception as exc:
        print(redact(exc, cfg), file=sys.stderr)
        return 1
    finally:
        if runtime is not None and runtime.thread.ident is not None:
            if not runtime.closed.is_set() and runtime.loop is not None:
                runtime.command('shutdown').result()
            runtime.thread.join()
        if lock is not None:
            lock.unlock()
        del qt_app


if __name__ == '__main__':
    raise SystemExit(main())
