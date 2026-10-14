"""Server-side helpers called by the CLI over SSH: `python -m phoenix.ctl status|log`."""

import sys

from . import config
from .db import Store
from .packages import package_dirs
from .state import events_text, status_text


def main() -> None:
    cfg = config.load()
    store = Store(cfg.db_path)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(status_text(store, len(package_dirs(cfg.packages_dir))))
    elif cmd == "log":
        print(events_text(store, 50))
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
