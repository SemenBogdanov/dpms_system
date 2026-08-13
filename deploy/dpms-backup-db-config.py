#!/usr/bin/env python3
"""Create transient pg_dump connection files without printing credentials."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: dpms-backup-db-config.py OUTPUT_DIR")

    output_dir = Path(sys.argv[1]).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = json.load(sys.stdin)
    if not isinstance(environment, list):
        raise SystemExit("docker environment payload must be a list")

    raw_url = next(
        (item.removeprefix("DATABASE_URL=") for item in environment if item.startswith("DATABASE_URL=")),
        None,
    )
    if not raw_url:
        raise SystemExit("DATABASE_URL is not configured in the backend container")

    normalized_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlsplit(normalized_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit("DATABASE_URL is not PostgreSQL")
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise SystemExit("DATABASE_URL must contain host, username, and password")

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise SystemExit("DATABASE_URL must contain a database name")
    host = unquote(parsed.hostname)
    port = parsed.port or 5432
    username = unquote(parsed.username)
    password = unquote(parsed.password)
    sslmode = parse_qs(parsed.query).get("sslmode", ["prefer"])[0]

    pgpass_path = output_dir / ".pgpass"
    pgpass_path.write_text(
        ":".join(
            pgpass_escape(value)
            for value in (host, str(port), database, username, password)
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(pgpass_path, 0o600)

    connection_path = output_dir / "db-connection.json"
    connection_path.write_text(
        json.dumps(
            {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "sslmode": sslmode,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(connection_path, 0o600)


if __name__ == "__main__":
    main()
