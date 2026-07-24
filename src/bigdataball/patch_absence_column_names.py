# patch_absence_column_names.py
# One-time migration: rename player_absences.GAME_DATE -> DATE and
# player_absences.PLAYER_NAME -> PLAYER so the table matches the repo-wide
# log-table column convention (player_logs / fantasy_logs use DATE, PLAYER).
#
# The original plan-013 ingestion kept the sanitized DNP-DND-NWT sheet
# headers as-is; absence_ingestion.py now renames them at ingest, so any
# table rows loaded before that fix carry the old column names. This script
# brings an already-populated table in line. Safe to re-run: if the columns
# are already renamed it reports and exits without touching the DB.
#
# Usage:
#   python patch_absence_column_names.py
import os
import sqlite3
import sys
from datetime import datetime

from . import paths

TABLE = "player_absences"
RENAMES = [
    ("GAME_DATE", "DATE"),
    ("PLAYER_NAME", "PLAYER"),
]

BASE_DATA_PATH = paths.resolve_base_data_path()
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")


def get_columns(conn):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}


def backup_db(conn):
    """Snapshot the live DB with SQLite's native backup API (handles WAL)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{DB_PATH}.bak-{stamp}"
    dest = sqlite3.connect(backup_path)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    print(f"Backed up database to: {backup_path}")


def main():
    if sqlite3.sqlite_version_info < (3, 25, 0):
        print(
            f"SQLite {sqlite3.sqlite_version} lacks ALTER TABLE ... RENAME COLUMN "
            "(needs 3.25+). Aborting."
        )
        return 1

    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Database: {DB_PATH}")
        cols = get_columns(conn)
        if not cols:
            print(f"Table '{TABLE}' does not exist. Nothing to migrate.")
            return 1

        pending = [(old, new) for old, new in RENAMES if old in cols]
        already = [(old, new) for old, new in RENAMES if new in cols]
        unaccounted = [
            (old, new) for old, new in RENAMES if old not in cols and new not in cols
        ]
        if unaccounted:
            print(
                f"ERROR: neither old nor new name present for {unaccounted} "
                f"(table has: {sorted(cols)}). Aborting without changes."
            )
            return 1
        if not pending:
            print(f"Columns already migrated ({[n for _, n in already]}). Nothing to do.")
            return 0

        backup_db(conn)
        for old, new in pending:
            conn.execute(f'ALTER TABLE {TABLE} RENAME COLUMN "{old}" TO "{new}"')
            print(f"Renamed {TABLE}.{old} -> {new}")
        conn.commit()

        final_cols = get_columns(conn)
        missing = [new for _, new in RENAMES if new not in final_cols]
        leftover = [old for old, _ in RENAMES if old in final_cols]
        if missing or leftover:
            print(
                f"ERROR: verification failed (missing {missing}, leftover {leftover}). "
                "Restore from the backup above."
            )
            return 1
        print(f"Done. {TABLE} columns: {sorted(final_cols)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
