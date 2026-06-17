import importlib
import os
import sqlite3
import sys

import pytest


@pytest.fixture
def dedup_tool(tmp_path, monkeypatch):
    """Import check_ingest_duplicates fresh with BASE_DATA_PATH / DB_PATH pointed at
    a temp dir, so main() and backup_db() operate on a throwaway database."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

    # Fresh import so the module-level path resolution re-runs with the env var.
    sys.modules.pop("check_ingest_duplicates", None)
    module = importlib.import_module("check_ingest_duplicates")

    yield module

    sys.modules.pop("check_ingest_duplicates", None)


def _seed(db_path, player_rows, fantasy_rows=()):
    """Create player_logs / fantasy_logs and insert the given rows.
    *_rows: iterables of (PLAYER_ID, PLAYER, DATE, value)."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE player_logs (PLAYER_ID INT, PLAYER TEXT, DATE TEXT, PTS INT)")
    conn.executemany("INSERT INTO player_logs VALUES (?,?,?,?)", list(player_rows))
    conn.execute(
        "CREATE TABLE fantasy_logs (PLAYER_ID INT, PLAYER TEXT, DATE TEXT, DK_POINTS REAL)"
    )
    conn.executemany("INSERT INTO fantasy_logs VALUES (?,?,?,?)", list(fantasy_rows))
    conn.commit()
    conn.close()


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _backups(data_dir):
    return [f for f in os.listdir(data_dir) if ".bak-" in f]


# Player 1 has 11-01 and 11-02 duplicated (exact copies); 11-03 unique; player 2 clean.
DUP_ROWS = [
    (1, "Alpha", "2025-11-01", 30),
    (1, "Alpha", "2025-11-02", 25),
    (1, "Alpha", "2025-11-01", 30),
    (1, "Alpha", "2025-11-02", 25),
    (1, "Alpha", "2025-11-03", 28),
    (2, "Beta", "2025-11-01", 10),
]


def test_get_stats_counts_duplicates(dedup_tool):
    mod = dedup_tool
    _seed(mod.DB_PATH, DUP_ROWS)
    conn = sqlite3.connect(mod.DB_PATH)
    try:
        total_rows, distinct_games, distinct_full_rows = mod.get_stats(conn, "player_logs")
    finally:
        conn.close()
    assert total_rows == 6
    assert distinct_games == 4              # extra_rows = 6 - 4 = 2
    assert distinct_full_rows == 4          # duplicates are exact copies -> safe to remove


def test_report_only_exits_nonzero_and_leaves_db_untouched(dedup_tool, monkeypatch):
    mod = dedup_tool
    _seed(mod.DB_PATH, [
        (1, "Alpha", "2025-11-01", 30),
        (1, "Alpha", "2025-11-01", 30),
    ])
    monkeypatch.setattr(sys, "argv", ["check_ingest_duplicates.py"])
    assert mod.main() == 1                  # duplicates present -> non-zero exit
    assert _count(mod.DB_PATH, "player_logs") == 2      # report-only: nothing deleted
    assert _backups(os.path.dirname(mod.DB_PATH)) == []  # and no backup written


def test_remove_dedupes_and_writes_backup(dedup_tool, monkeypatch):
    mod = dedup_tool
    _seed(mod.DB_PATH, DUP_ROWS)
    monkeypatch.setattr(sys, "argv", ["check_ingest_duplicates.py", "--remove"])
    assert mod.main() == 0
    assert _count(mod.DB_PATH, "player_logs") == 4      # one row per (PLAYER_ID, DATE)

    # No (PLAYER_ID, DATE) group has more than one row left.
    conn = sqlite3.connect(mod.DB_PATH)
    try:
        dups = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM player_logs "
            'GROUP BY "PLAYER_ID", "DATE" HAVING COUNT(*) > 1)'
        ).fetchone()[0]
    finally:
        conn.close()
    assert dups == 0
    assert len(_backups(os.path.dirname(mod.DB_PATH))) == 1  # backup taken before delete


def test_remove_on_clean_db_is_noop(dedup_tool, monkeypatch):
    mod = dedup_tool
    _seed(mod.DB_PATH, [
        (1, "Alpha", "2025-11-01", 30),
        (1, "Alpha", "2025-11-02", 25),
    ])
    monkeypatch.setattr(sys, "argv", ["check_ingest_duplicates.py", "--remove"])
    assert mod.main() == 0                  # no duplicates -> success
    assert _count(mod.DB_PATH, "player_logs") == 2      # unchanged
    assert _backups(os.path.dirname(mod.DB_PATH)) == []  # nothing removed -> no backup
