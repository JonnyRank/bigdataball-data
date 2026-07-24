"""create_log_indexes.py

Create the UNIQUE index on (PLAYER_ID, DATE) for `player_logs`, `fantasy_logs`,
and `player_absences` -- a one-off backfill for an existing database.

Why this exists
---------------
Plan 012 adds a DB-level UNIQUE index on each log table so a duplicate insert
fails loudly with an IntegrityError instead of silently inflating every average.
The pipeline code (daily_player_upload.py / daily_fantasy_log_upload.py /
absence_ingestion.py) creates those indexes automatically -- but only when it
runs. `fantasy_logs` and `player_logs` get indexed on any pipeline run (their
`ensure_unique_index()` sits in the unconditional `initialize_database()` path),
while `player_absences` is indexed only on a run that actually ingests a file
(its `ensure_unique_index()` is inside `ingest_absences()`, called per file).

During the offseason there is no pipeline run and no file to ingest, so none of
the three indexes would be created until the first run of the new season. This
script creates all three now, directly against the already-populated tables --
no pipeline run, no data ingested, no rows touched. It produces the exact same
index names and columns the pipeline code produces
(`idx_<table>_player_date` UNIQUE on ("PLAYER_ID", "DATE")), so once the plan-012
code does run, its `CREATE UNIQUE INDEX IF NOT EXISTS` simply no-ops.

Safe to run repeatedly (idempotent) and safe to run before OR after the plan-012
code is merged -- it depends only on `paths` and sqlite3, not on the new code.

Usage
-----
    python create_log_indexes.py                 # create indexes on all three tables
    python create_log_indexes.py --table player_absences   # one table only

Prerequisite: the tables must be free of duplicate (PLAYER_ID, DATE) rows, or the
UNIQUE index creation fails. This script checks first and refuses to touch a table
that still has duplicates, pointing you at check_ingest_duplicates.py --remove.

Manual SQL equivalent (per table)
---------------------------------
    CREATE UNIQUE INDEX IF NOT EXISTS idx_player_absences_player_date
    ON player_absences ("PLAYER_ID", "DATE");
"""

import argparse
import os
import sqlite3
import sys
from . import paths

# --- Configuration ---
BASE_DATA_PATH = paths.resolve_base_data_path()

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")

# Tables whose natural unique key is (PLAYER_ID, DATE) -- same list as
# check_ingest_duplicates.py.
LOG_TABLES = ["player_logs", "fantasy_logs", "player_absences"]

KEY_COLUMNS = ("PLAYER_ID", "DATE")


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def require_key_columns(conn, table):
    """Fail loudly if the key columns are missing from the table.

    SQLite silently treats a double-quoted identifier that matches no column as a
    STRING LITERAL, so a UNIQUE index on a mistyped/absent column would index a
    constant instead of the intended key. Guarding here turns that into a crash.
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = [c for c in KEY_COLUMNS if c not in cols]
    if missing:
        raise RuntimeError(
            f"Table '{table}' is missing key column(s) {missing} "
            f"(has: {sorted(cols)}). Refusing to create the index."
        )


def duplicate_count(conn, table):
    """Return how many rows exceed one per (PLAYER_ID, DATE) -- 0 means clean."""
    total_rows, distinct_games = conn.execute(
        f"""SELECT COUNT(*), COUNT(DISTINCT "PLAYER_ID" || '_' || "DATE") FROM {table}"""
    ).fetchone()
    return total_rows - distinct_games


def index_name(table):
    return f"idx_{table}_player_date"


def create_index(conn, table):
    """Create the UNIQUE (PLAYER_ID, DATE) index on one table.

    Returns one of: "created", "exists", "skipped-missing", "skipped-duplicates".
    """
    print(f"\n=== {table} ===")
    if not table_exists(conn, table):
        print("  Table does not exist yet -- nothing to index (the pipeline will")
        print("  create both the table and its index on the first ingestion run).")
        return "skipped-missing"

    require_key_columns(conn, table)

    name = index_name(table)
    existing = {
        row[1] for row in conn.execute(f"PRAGMA index_list({table})")
    }  # row[1] is the index name
    if name in existing:
        print(f"  Index '{name}' already exists -- nothing to do.")
        return "exists"

    dupes = duplicate_count(conn, table)
    if dupes:
        print(
            f"  REFUSING to create the index: {dupes} duplicate (PLAYER_ID, DATE) "
            "row(s) present.\n"
            "  A UNIQUE index cannot be built over duplicates. Clean them first:\n"
            f"      python check_ingest_duplicates.py --table {table}\n"
            f"      python check_ingest_duplicates.py --remove   # backs up the DB first\n"
            "  then rebuild derived data and re-run this script."
        )
        return "skipped-duplicates"

    conn.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ("PLAYER_ID", "DATE")'
    )
    conn.commit()
    print(f"  Created UNIQUE index '{name}' on (\"PLAYER_ID\", \"DATE\").")
    return "created"


def main():
    parser = argparse.ArgumentParser(
        description="Create the UNIQUE (PLAYER_ID, DATE) index on the log tables "
        "(one-off backfill for plan 012)."
    )
    parser.add_argument(
        "--table",
        choices=LOG_TABLES + ["all"],
        default="all",
        help="Table to index (player_logs | fantasy_logs | player_absences | all).",
    )
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return 1

    tables = LOG_TABLES if args.table == "all" else [args.table]

    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Database: {DB_PATH}")
        results = {t: create_index(conn, t) for t in tables}

        print("\n--- Summary ---")
        for table, outcome in results.items():
            print(f"  {table:<18} {outcome}")

        # Non-zero exit if any table was skipped because of duplicates, so the
        # result is composable in a shell/CI pipeline.
        blocked = [t for t, o in results.items() if o == "skipped-duplicates"]
        if blocked:
            print(
                f"\n{len(blocked)} table(s) still have duplicates and were not "
                f"indexed: {blocked}. See the message above."
            )
            return 1
        print("\nDone. All requested tables have the UNIQUE (PLAYER_ID, DATE) index.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
