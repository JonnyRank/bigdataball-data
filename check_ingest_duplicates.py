"""check_ingest_duplicates.py

Detect (and optionally remove) duplicate game-log rows in `player_logs`,
`fantasy_logs`, and `player_absences` caused by the de-duplication bug
described in issue #6.

Background
----------
`daily_player_upload.py` / `daily_fantasy_log_upload.py` de-duplicate logs with
an in-memory `existing_log_keys` set, but rebuild that set *inside* the per-file
loop from a startup DB snapshot. The `.update(newly_added_keys)` at the end of
each iteration is therefore wiped at the top of the next iteration. When a single
run ingests two or more cumulative `.xlsx` files (the pipeline ran after missing
a day), rows from the first file get re-inserted from each later file.

Neither table has a PRIMARY KEY or UNIQUE constraint, so nothing at the DB level
prevents the duplicates. The natural unique key is (PLAYER_ID, DATE) -- one NBA
game per player per day. `log_key` is computed in memory only and is not stored,
so detection groups on PLAYER_ID, DATE directly.

Usage
-----
Report only (read-only, no writes) -- run this first:

    python check_ingest_duplicates.py                      # both tables
    python check_ingest_duplicates.py --table player_logs  # one table only

Remove duplicates (backs up the DB to a timestamped .bak-* first, then deletes):

    python check_ingest_duplicates.py --remove

Only `--remove` writes to the database; without it the script just reports.

Manual SQL equivalents
----------------------
Detection (run per table -- player_logs, fantasy_logs):

    -- summary: how many extra rows exist
    SELECT COUNT(*)                                            AS total_rows,
           COUNT(DISTINCT PLAYER_ID || '_' || DATE)            AS distinct_games,
           COUNT(*) - COUNT(DISTINCT PLAYER_ID || '_' || DATE) AS extra_rows
    FROM player_logs;

    -- list the duplicated games
    SELECT PLAYER_ID, DATE, COUNT(*) AS copies
    FROM player_logs
    GROUP BY PLAYER_ID, DATE
    HAVING COUNT(*) > 1
    ORDER BY copies DESC, DATE DESC;

    -- safety: are the duplicates exact copies? (equal -> safe to auto-remove)
    SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM player_logs)) AS distinct_full_rows,
           COUNT(DISTINCT PLAYER_ID || '_' || DATE)                    AS distinct_games
    FROM player_logs;

Removal (back up nba_fantasy_logs.db first):

    DELETE FROM player_logs
    WHERE rowid NOT IN (SELECT MIN(rowid) FROM player_logs  GROUP BY PLAYER_ID, DATE);

    DELETE FROM fantasy_logs
    WHERE rowid NOT IN (SELECT MIN(rowid) FROM fantasy_logs GROUP BY PLAYER_ID, DATE);

After removing rows, rebuild the derived data (games-played and every average
were inflated):

    python create_summary_tables.py
    python export_slate_averages_vw.py
    python export_playoffs_slate_averages_vw.py
    python export_slate_averages_csv.py
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
import paths

# --- Configuration ---
BASE_DATA_PATH = paths.resolve_base_data_path()

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")

# Tables whose natural unique key is (PLAYER_ID, DATE).
LOG_TABLES = ["player_logs", "fantasy_logs", "player_absences"]

KEY_COLUMNS = ("PLAYER_ID", "DATE")


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def require_key_columns(conn, table):
    """Fail loudly if the key columns are missing from the table.

    SQLite silently treats a double-quoted identifier that matches no column
    as a STRING LITERAL, so e.g. GROUP BY "PLAYER_ID", "DATE" against a table
    without a DATE column groups every row per player under the constant
    'DATE' — producing a wall of bogus "duplicates" instead of an error.
    Guarding here turns that failure mode into an explicit crash.
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = [c for c in KEY_COLUMNS if c not in cols]
    if missing:
        raise RuntimeError(
            f"Table '{table}' is missing key column(s) {missing} "
            f"(has: {sorted(cols)}). Refusing to check/remove duplicates — "
            "without this guard SQLite would treat the quoted column name as "
            "a string literal and report nonsense duplicates."
        )


def get_stats(conn, table):
    """Return (total_rows, distinct_games, distinct_full_rows) for a table."""
    total_rows, distinct_games = conn.execute(
        f"""SELECT COUNT(*), COUNT(DISTINCT "PLAYER_ID" || '_' || "DATE") FROM {table}"""
    ).fetchone()
    (distinct_full_rows,) = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table})"
    ).fetchone()
    return total_rows, distinct_games, distinct_full_rows


def report(conn, table):
    """Print a duplicate report for one table. Returns extra_rows count."""
    print(f"\n=== {table} ===")
    if not table_exists(conn, table):
        print("  Table does not exist (nothing to check).")
        return 0

    require_key_columns(conn, table)
    total_rows, distinct_games, distinct_full_rows = get_stats(conn, table)
    extra_rows = total_rows - distinct_games

    print(f"  total_rows     : {total_rows}")
    print(f"  distinct_games : {distinct_games}  (unique PLAYER_ID + DATE)")
    print(f"  extra_rows     : {extra_rows}")

    if extra_rows == 0:
        print("  No duplicate (PLAYER_ID, DATE) rows found.")
        return 0

    # Worst-offending duplicate groups.
    dup_groups = conn.execute(
        f"""
        SELECT "PLAYER_ID", "DATE", COUNT(*) AS copies
        FROM {table}
        GROUP BY "PLAYER_ID", "DATE"
        HAVING COUNT(*) > 1
        ORDER BY copies DESC, "DATE" DESC
        LIMIT 20
        """
    ).fetchall()
    print(f"\n  Duplicate games (top {len(dup_groups)} by copy count):")
    print(f"    {'PLAYER_ID':<12} {'DATE':<12} copies")
    for player_id, date, copies in dup_groups:
        print(f"    {str(player_id):<12} {str(date):<12} {copies}")

    # Safety check: are duplicates byte-for-byte copies?
    if distinct_full_rows == distinct_games:
        print(
            "\n  Safety check: all duplicates are exact copies "
            "(distinct_full_rows == distinct_games) -> safe to auto-remove."
        )
    else:
        print(
            "\n  WARNING: some same-(PLAYER_ID, DATE) rows differ in other columns "
            f"(distinct_full_rows={distinct_full_rows} > distinct_games={distinct_games})."
            "\n  Review these manually before removing; --remove keeps the earliest "
            "(MIN rowid) copy of each game."
        )

    return extra_rows


def remove(conn, table):
    """Delete duplicate rows in one table, keeping the earliest rowid per game."""
    if not table_exists(conn, table):
        print(f"\n=== {table} === (does not exist, skipping)")
        return

    require_key_columns(conn, table)
    before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.execute(
        f"""
        DELETE FROM {table}
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM {table} GROUP BY "PLAYER_ID", "DATE"
        )
        """
    )
    conn.commit()
    after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"\n=== {table} === removed {before - after} rows ({before} -> {after})")


def backup_db(conn):
    """Snapshot the live DB with SQLite's native backup API (handles WAL)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{DB_PATH}.bak-{stamp}"
    dest = sqlite3.connect(backup_path)
    try:
        conn.backup(dest)  # handles its own locking; no transaction wrapper needed
    finally:
        dest.close()
    print(f"Backed up database to: {backup_path}")
    return backup_path


def main():
    parser = argparse.ArgumentParser(
        description="Detect/remove duplicate (PLAYER_ID, DATE) rows from issue #6."
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Back up the DB, then delete duplicates (default is report-only).",
    )
    parser.add_argument(
        "--table",
        choices=LOG_TABLES + ["all"],
        default="all",
        help="Table to check/remove (player_logs | fantasy_logs | player_absences | all).",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM after removal to reclaim disk space.",
    )
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return 1

    tables = LOG_TABLES if args.table == "all" else [args.table]

    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Database: {DB_PATH}")
        print("--- Duplicate report ---")
        extra_total = sum(report(conn, t) for t in tables)

        if not args.remove:
            print("\n(Report only. Re-run with --remove to delete duplicates.)")
            # Non-zero exit when duplicates exist, so the report is composable in
            # shell/CI pipelines.
            return 1 if extra_total else 0

        if extra_total == 0:
            print("\nNo duplicates to remove. Database left unchanged.")
            return 0

        print("\n--- Removing duplicates ---")
        # The backup is the safety net for this destructive op: if it fails,
        # abort before deleting anything rather than dumping a raw traceback.
        try:
            backup_db(conn)
        except (sqlite3.Error, OSError) as e:
            print(f"\nBackup failed ({e}). Aborting without removing any rows.")
            return 1
        for table in tables:
            remove(conn, table)

        if args.vacuum:
            print("\nRunning VACUUM...")
            # VACUUM cannot run inside a transaction; force autocommit for it.
            old_isolation = conn.isolation_level
            conn.isolation_level = None
            try:
                conn.execute("VACUUM")
            finally:
                conn.isolation_level = old_isolation

        print("\n--- Re-checking ---")
        remaining = sum(report(conn, t) for t in tables)
        if remaining == 0:
            print("\nDone. No duplicate (PLAYER_ID, DATE) rows remain.")
            print(
                "Rebuild derived data next: create_summary_tables.py, "
                "export_slate_averages_vw.py, export_playoffs_slate_averages_vw.py, "
                "export_slate_averages_csv.py"
            )
            return 0
        print(f"\nWARNING: {remaining} extra rows still remain after removal.")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
