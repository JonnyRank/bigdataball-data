import os
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


def test_distinct_team_names_prefers_fantasy_logs(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE fantasy_logs (TEAM TEXT)")
    conn.execute("INSERT INTO fantasy_logs VALUES ('Boston')")
    conn.execute("INSERT INTO fantasy_logs VALUES ('Denver')")
    conn.execute("INSERT INTO fantasy_logs VALUES (NULL)")  # nulls filtered out
    conn.execute("CREATE TABLE player_logs (TEAM TEXT)")
    conn.execute("INSERT INTO player_logs VALUES ('Miami')")  # should be ignored
    conn.commit()
    result = seed_map_teams._distinct_team_names(conn)
    assert "Boston" in result
    assert "Denver" in result
    assert None not in result
    assert "Miami" not in result  # player_logs not used when fantasy_logs has rows
    conn.close()


def test_distinct_team_names_falls_through_to_player_logs(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    # fantasy_logs exists but has no TEAM rows — fall through to player_logs
    conn.execute("CREATE TABLE fantasy_logs (PLAYER TEXT)")  # no TEAM column
    conn.execute("CREATE TABLE player_logs (TEAM TEXT)")
    conn.execute("INSERT INTO player_logs VALUES ('Miami')")
    conn.commit()
    result = seed_map_teams._distinct_team_names(conn)
    assert result == ["Miami"]
    conn.close()


def test_distinct_team_names_empty_when_no_tables(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    assert seed_map_teams._distinct_team_names(conn) == []
    conn.close()


def test_canonical_rows_yields_30_unique_abbreviations():
    rows = seed_map_teams._canonical_rows()
    abbrs = [abbr for _, abbr in rows]
    assert len(set(abbrs)) == 30, f"expected 30 unique abbreviations, got {set(abbrs)}"
    assert len(rows) == 30


def test_main_derives_rows_from_fantasy_logs(tmp_path):
    db = tmp_path / "nba_fantasy_logs.db"  # main() always opens this filename
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE fantasy_logs (TEAM TEXT)")
    conn.execute("INSERT INTO fantasy_logs VALUES ('Boston Celtics')")
    conn.execute("INSERT INTO fantasy_logs VALUES ('Unknown Squad')")
    conn.commit()
    conn.close()

    os.environ["BIGDATABALL_DATA_DIR"] = str(tmp_path)
    try:
        # main() should exit 1 due to the unmatched team
        with pytest.raises(SystemExit) as exc_info:
            seed_map_teams.main()
        assert exc_info.value.code == 1
    finally:
        del os.environ["BIGDATABALL_DATA_DIR"]

    conn2 = sqlite3.connect(db)
    rows = conn2.execute(
        "SELECT RAW_TEAM_NAME, TEAM_ABBREVIATION FROM map_teams ORDER BY RAW_TEAM_NAME"
    ).fetchall()
    conn2.close()
    assert ("Boston Celtics", "BOS") in rows
    assert ("Unknown Squad", None) in rows
