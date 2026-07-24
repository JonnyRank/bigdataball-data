"""Tests for the one-time migration script patch_fantasy_id_types.py.

The migration is the riskier half of plan 014 (backup, drop-null, fractional
rejection, if_exists="replace" affinity rebuild, atomic UNIQUE-index recreation)
and cannot be exercised against the live DB from CI, so these seed a synthetic
FLOAT-affinity fantasy_logs table in a temp dir and drive main() end to end.

The seeded table includes a GAME_ID column, giving real INTEGER-affinity
coverage for GAME_ID that the shared write_fantasy_xlsx fixture (no GAME_ID
column) cannot provide.
"""
import glob
import importlib
import os
import sqlite3
import sys

import pandas as pd
import pytest


def _seed_fantasy_logs(db_path, *, affinity, player_id=12345.0, game_id=22500001.0,
                       date="2025-11-01", with_index=True):
    """Create a fantasy_logs table with the given ID-column affinity ('REAL' or
    'INTEGER'), one row, and (optionally) plan 012's UNIQUE index."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f'CREATE TABLE fantasy_logs ('
            f'"PLAYER_ID" {affinity}, "GAME_ID" {affinity}, '
            f'"DATE" TEXT, "PLAYER" TEXT)'
        )
        if with_index:
            conn.execute(
                'CREATE UNIQUE INDEX idx_fantasy_logs_player_date '
                'ON fantasy_logs ("PLAYER_ID", "DATE")'
            )
        conn.execute(
            'INSERT INTO fantasy_logs ("PLAYER_ID", "GAME_ID", "DATE", "PLAYER") '
            'VALUES (?, ?, ?, ?)',
            (player_id, game_id, date, "Alpha Player"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def patch_module(tmp_path, monkeypatch):
    """Import patch_fantasy_id_types fresh with DB_PATH pointed under a temp dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    sys.modules.pop("bigdataball.patch_fantasy_id_types", None)
    sys.modules.pop("bigdataball.paths", None)
    module = importlib.import_module("bigdataball.patch_fantasy_id_types")
    yield module
    sys.modules.pop("bigdataball.patch_fantasy_id_types", None)


def _typeof(db_path, column):
    conn = sqlite3.connect(db_path)
    try:
        return [
            r[0]
            for r in conn.execute(
                f'SELECT DISTINCT typeof("{column}") FROM fantasy_logs'
            ).fetchall()
        ]
    finally:
        conn.close()


def test_migration_flips_affinity_preserves_data_and_index(patch_module):
    mod = patch_module
    _seed_fantasy_logs(mod.DB_PATH, affinity="REAL")

    # Sanity: the seeded table really is REAL-affinity before we migrate.
    assert _typeof(mod.DB_PATH, "PLAYER_ID") == ["real"]

    rc = mod.main()
    assert rc == 0

    # Both ID columns are now INTEGER affinity.
    assert _typeof(mod.DB_PATH, "PLAYER_ID") == ["integer"]
    assert _typeof(mod.DB_PATH, "GAME_ID") == ["integer"]

    conn = sqlite3.connect(mod.DB_PATH)
    try:
        # Row count preserved and values intact (no truncation, DATE untouched).
        row = conn.execute(
            'SELECT "PLAYER_ID", "GAME_ID", "DATE", "PLAYER" FROM fantasy_logs'
        ).fetchall()
        assert row == [(12345, 22500001, "2025-11-01", "Alpha Player")]
        # Plan 012's UNIQUE index survived the if_exists="replace" rebuild.
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_fantasy_logs_player_date'"
        ).fetchone()
        assert idx is not None
    finally:
        conn.close()

    # A backup copy was written before the rewrite.
    assert glob.glob(f"{mod.DB_PATH}.bak-*"), "expected a .bak-<timestamp> backup"


def test_migration_is_idempotent_and_skips_backup(patch_module):
    mod = patch_module
    _seed_fantasy_logs(mod.DB_PATH, affinity="INTEGER", player_id=12345, game_id=22500001)

    rc = mod.main()
    assert rc == 0

    # Already-INTEGER table: the short-circuit must not back up or rewrite.
    assert _typeof(mod.DB_PATH, "PLAYER_ID") == ["integer"]
    assert not glob.glob(f"{mod.DB_PATH}.bak-*"), "idempotent run must not back up"


def test_migration_rejects_fractional_id(patch_module):
    mod = patch_module
    _seed_fantasy_logs(mod.DB_PATH, affinity="REAL", player_id=12345.7)

    with pytest.raises(ValueError, match="non-integer"):
        mod.main()
