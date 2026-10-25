"""Explicit backup/restore for the portable SQLite DEMO adapter."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.config import PROJECT_ROOT, get_settings


def _database_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("This CLI supports only SQLite DEMO; use pg_dump/pg_restore for PostgreSQL")
    path = Path(url.removeprefix("sqlite:///"))
    return path if path.is_absolute() else PROJECT_ROOT / path


def backup(destination: Path | None = None) -> Path:
    source = _database_path().resolve()
    if not source.exists():
        raise SystemExit(f"DEMO database does not exist: {source}")
    destination = (destination or PROJECT_ROOT / "backups" / f"demo-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db").resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source == destination:
        raise SystemExit("Backup destination must differ from the live database")
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as destination_db:
        source_db.backup(destination_db)
        result = destination_db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Backup integrity check failed: {result}")
    return destination


def restore(source: Path) -> Path:
    source = source.resolve()
    target = _database_path().resolve()
    if not source.is_file():
        raise SystemExit(f"Backup does not exist: {source}")
    if source == target:
        raise SystemExit("Restore source must differ from the live database")
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_db:
        result = source_db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Source integrity check failed: {result}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as target_db:
            source_db.backup(target_db)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup or restore the persistent SQLite DEMO database")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backup", nargs="?", const="", metavar="PATH", help="Create a consistent backup")
    action.add_argument("--restore", metavar="PATH", help="Explicitly overwrite DEMO DB from a checked backup")
    args = parser.parse_args()
    if args.restore:
        print(f"Restored: {restore(Path(args.restore))}")
    else:
        destination = Path(args.backup) if args.backup else None
        print(f"Backup: {backup(destination)}")


if __name__ == "__main__":
    main()
