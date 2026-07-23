# patch_fantasy_id_types.py
# One-time migration: rewrite fantasy_logs.PLAYER_ID (and GAME_ID, if present)
# from FLOAT/REAL to INTEGER affinity, matching player_logs / player_absences.
#
# Root cause (see plans/014): daily_fantasy_log_upload.py used to create
# fantasy_logs with a bare to_sql (no dtype=, no cast); pandas infers float64
# for any numeric column containing a blank/NaN cell, so the column landed
# with REAL affinity. daily_fantasy_log_upload.py now casts incoming IDs to
# int and passes an explicit dtype on insert, but that only affects *new*
# rows / a first-run table creation -- it does not change the affinity of an
# already-existing fantasy_logs table. This script rewrites the existing
# table so historical rows match.
#
# A plain `UPDATE ... SET PLAYER_ID = CAST(...)` does NOT stick -- SQLite
# re-coerces the value back to REAL on store because the column's affinity
# is REAL. Changing affinity requires recreating the table with an explicit
# type, which is what this script does via to_sql(if_exists="replace",
# dtype=...). Because that DROPS the table (and with it plan 012's UNIQUE
# index on (PLAYER_ID, DATE)), the rebuild and the index re-creation are
# done inside the same transaction so the table is never left without its
# uniqueness guard.
#
# The DB is backed up first (same .bak-<timestamp> habit as
# check_ingest_duplicates.py / patch_absence_column_names.py) since
# if_exists="replace" drops the table.
#
# Usage:
#   python patch_fantasy_id_types.py
import os
import sqlite3
import sys
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text, Integer

import paths

TABLE = "fantasy_logs"
ID_COLS_CANDIDATES = ("PLAYER_ID", "GAME_ID")
INDEX_NAME = "idx_fantasy_logs_player_date"

BASE_DATA_PATH = paths.resolve_base_data_path()
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")


def backup_db():
    """Snapshot the live DB with SQLite's native backup API (handles WAL)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{DB_PATH}.bak-{stamp}"
    src = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(backup_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    print(f"Backed up database to: {backup_path}")


def already_integer(engine):
    """True if every present ID column already reports INTEGER storage
    class for every row (i.e. the migration has already run)."""
    with engine.connect() as conn:
        cols = {
            row[1]
            for row in conn.execute(text(f"PRAGMA table_info({TABLE})")).fetchall()
        }
        id_cols = [c for c in ID_COLS_CANDIDATES if c in cols]
        if not id_cols:
            return True, id_cols
        for c in id_cols:
            types = {
                row[0]
                for row in conn.execute(
                    text(f'SELECT DISTINCT typeof("{c}") FROM {TABLE}')
                ).fetchall()
            }
            if types - {"integer", "null"}:
                return False, id_cols
        return True, id_cols


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return 1

    engine = create_engine(f"sqlite:///{DB_PATH}")

    with engine.connect() as conn:
        table_exists = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
            ),
            {"t": TABLE},
        ).fetchone()
    if not table_exists:
        print(f"Table '{TABLE}' does not exist. Nothing to migrate.")
        return 1

    is_int, id_cols = already_integer(engine)
    if not id_cols:
        print(f"No ID columns {ID_COLS_CANDIDATES} present in {TABLE}. Nothing to do.")
        return 0
    if is_int:
        print(f"{id_cols} already stored as INTEGER in {TABLE}. Nothing to do.")
        return 0

    print(f"Database: {DB_PATH}")
    backup_db()

    df = pd.read_sql_table(TABLE, engine)
    id_cols = [c for c in ID_COLS_CANDIDATES if c in df.columns]
    before = len(df)
    df = df.dropna(subset=id_cols)
    dropped = before - len(df)
    if dropped:
        print(
            f"WARNING: dropped {dropped} {TABLE} row(s) with a missing "
            f"{id_cols} value."
        )
    for c in id_cols:
        # Reject fractional IDs rather than silently truncating them.
        frac = df[c][df[c] % 1 != 0]
        if not frac.empty:
            raise ValueError(
                f"{c} has non-integer values (refusing to truncate): "
                f"{frac.unique().tolist()}"
            )
        df[c] = df[c].astype(int)

    with engine.begin() as conn:
        df.to_sql(
            TABLE,
            conn,
            if_exists="replace",
            index=False,
            dtype={c: Integer() for c in id_cols},
        )
        conn.execute(
            text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} '
                f'ON {TABLE} ("PLAYER_ID", "DATE")'
            )
        )

    print(
        f"Rewrote {TABLE}: {len(df)} rows ({dropped} dropped), {id_cols} cast to "
        f"INTEGER; re-created UNIQUE {INDEX_NAME} in the same transaction."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
