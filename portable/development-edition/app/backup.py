"""Create a consistent SQLite backup while the application is running."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.database import DATABASE_PATH


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.backup /data/backups/name.sqlite3")
    destination = Path(sys.argv[1]).resolve()
    data_root = DATABASE_PATH.parent.resolve()
    if data_root not in destination.parents:
        raise SystemExit("backup destination must be inside the data directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise SystemExit("backup integrity check failed")
    print(destination)


if __name__ == "__main__":
    main()
