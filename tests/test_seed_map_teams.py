import sqlite3

import pytest

import seed_map_teams


def test_normalize_collapses_and_lowercases():
    assert seed_map_teams.normalize("  Golden   State ") == "golden state"


def test_known_team_resolves_to_abbreviation():
    assert seed_map_teams.TEAM_ABBREVIATIONS[seed_map_teams.normalize("Boston Celtics")] == "BOS"


def test_write_map_teams_schema(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    seed_map_teams.write_map_teams(conn, [("Boston", "BOS"), ("Mystery Team", None)])
    cols = [r[1] for r in conn.execute("PRAGMA table_info(map_teams)")]
    assert cols == ["RAW_TEAM_NAME", "TEAM_ABBREVIATION"]
    rows = conn.execute(
        "SELECT RAW_TEAM_NAME, TEAM_ABBREVIATION FROM map_teams ORDER BY RAW_TEAM_NAME"
    ).fetchall()
    assert rows == [("Boston", "BOS"), ("Mystery Team", None)]
    conn.close()


def test_write_map_teams_refuses_to_overwrite_without_force(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    seed_map_teams.write_map_teams(conn, [("Boston", "BOS")])  # first write: empty -> ok
    with pytest.raises(RuntimeError):
        seed_map_teams.write_map_teams(conn, [("Denver", "DEN")])  # populated -> refused
    # force=True overwrites
    seed_map_teams.write_map_teams(conn, [("Denver", "DEN")], force=True)
    rows = conn.execute("SELECT RAW_TEAM_NAME FROM map_teams").fetchall()
    assert rows == [("Denver",)]
    conn.close()
