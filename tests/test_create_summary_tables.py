# tests/test_create_summary_tables.py
import importlib
import sqlite3
import sys

import pandas as pd
import pytest


@pytest.fixture
def summary_tables(tmp_path, monkeypatch):
    """Imports create_summary_tables fresh with BASE_DATA_PATH pointed at tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    sys.modules.pop("create_summary_tables", None)
    module = importlib.import_module("create_summary_tables")
    yield module
    module.engine.dispose()
    sys.modules.pop("create_summary_tables", None)


def _seed(db_path, fantasy_rows, players, teams):
    """Seed the three required tables directly via sqlite3.

    fantasy_rows: list of dicts with keys:
        PLAYER_ID, PLAYER, DATE, SEASON_SEGMENT, TEAM,
        DK_POINTS, DK_SALARY, MINUTES, STARTED, USAGE
    players: list of (PLAYER_ID, PLAYER_NAME)
    teams:   list of (RAW_TEAM_NAME, TEAM_ABBREVIATION)
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE fantasy_logs (
            PLAYER_ID INT, PLAYER TEXT, DATE TEXT, SEASON_SEGMENT TEXT,
            TEAM TEXT, DK_POINTS REAL, DK_SALARY REAL,
            MINUTES REAL, STARTED TEXT, USAGE REAL
        )
    """)
    conn.executemany(
        "INSERT INTO fantasy_logs VALUES (:PLAYER_ID,:PLAYER,:DATE,:SEASON_SEGMENT,"
        ":TEAM,:DK_POINTS,:DK_SALARY,:MINUTES,:STARTED,:USAGE)",
        fantasy_rows,
    )
    conn.execute("CREATE TABLE dim_players (PLAYER_ID INT PRIMARY KEY, PLAYER_NAME TEXT)")
    conn.executemany("INSERT INTO dim_players VALUES (?,?)", players)
    conn.execute("CREATE TABLE map_teams (RAW_TEAM_NAME TEXT PRIMARY KEY, TEAM_ABBREVIATION TEXT)")
    conn.executemany("INSERT INTO map_teams VALUES (?,?)", teams)
    conn.commit()
    conn.close()


REGULAR_SEGMENT = "2024-25 NBA Regular Season"
PLAYOFF_SEGMENT = "2025 NBA Playoffs"

BASE_ROW = {
    "PLAYER_ID": 1, "PLAYER": "Raw Name",  # PLAYER will be replaced by dim_players join
    "DATE": "2025-11-01", "SEASON_SEGMENT": REGULAR_SEGMENT,
    "TEAM": "Boston Celtics", "DK_POINTS": 40.0, "DK_SALARY": 8000,
    "MINUTES": 34.0, "STARTED": "Y", "USAGE": 28.0,
}


def test_missing_tables_returns_false(summary_tables):
    mod = summary_tables
    # DB exists but none of the required tables are created.
    result = mod.create_fantasy_averages_table()
    assert result is False


def test_basic_aggregation_creates_fantasy_averages(summary_tables):
    mod = summary_tables
    rows = [
        {**BASE_ROW, "DATE": "2025-11-01", "DK_POINTS": 40.0, "MINUTES": 34.0},
        {**BASE_ROW, "DATE": "2025-11-02", "DK_POINTS": 50.0, "MINUTES": 36.0},
    ]
    _seed(mod.DB_PATH, rows, [(1, "Canonical Name")], [("Boston Celtics", "BOS")])

    result = mod.create_fantasy_averages_table()
    assert result is True

    df = pd.read_sql_query("SELECT * FROM fantasy_averages", mod.engine)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["GP"] == 2
    assert abs(row["FPPG"] - 45.0) < 0.01          # (40 + 50) / 2
    assert row["SEASON"] == "2024-25"
    assert row["TEAM"] == "BOS"
    assert row["PLAYER"] == "Canonical Name"        # from dim_players, not fantasy_logs


def test_season_type_classification(summary_tables):
    mod = summary_tables
    rows = [
        {**BASE_ROW, "DATE": "2025-11-01", "SEASON_SEGMENT": REGULAR_SEGMENT},
        {**BASE_ROW, "DATE": "2025-05-01", "SEASON_SEGMENT": PLAYOFF_SEGMENT},
    ]
    _seed(mod.DB_PATH, rows, [(1, "Alpha Player")], [("Boston Celtics", "BOS")])

    mod.create_fantasy_averages_table()

    df = pd.read_sql_query("SELECT SEASON_TYPE, SEASON FROM fantasy_averages ORDER BY SEASON_TYPE", mod.engine)
    assert set(df["SEASON_TYPE"].tolist()) == {"Regular", "Playoffs"}
    # Regular season key format: "YYYY-YY"
    reg_row = df[df["SEASON_TYPE"] == "Regular"].iloc[0]
    assert reg_row["SEASON"] == "2024-25"
    # Playoff season key format: "YYYY"
    playoff_row = df[df["SEASON_TYPE"] == "Playoffs"].iloc[0]
    assert playoff_row["SEASON"] == "2025"


def test_l30fppm_excludes_old_games(summary_tables):
    mod = summary_tables
    today = pd.Timestamp.now().normalize()
    recent = (today - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    old = (today - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

    rows = [
        {**BASE_ROW, "DATE": recent,  "DK_POINTS": 60.0, "MINUTES": 30.0},
        {**BASE_ROW, "DATE": old,     "DK_POINTS": 0.0,  "MINUTES": 30.0},
    ]
    _seed(mod.DB_PATH, rows, [(1, "Alpha")], [("Boston Celtics", "BOS")])

    mod.create_fantasy_averages_table()

    df = pd.read_sql_query("SELECT L30FPPM, FPPM FROM fantasy_averages", mod.engine)
    assert len(df) == 1
    row = df.iloc[0]
    # L30FPPM should be 60/30 = 2.0 (recent game only)
    assert abs(row["L30FPPM"] - 2.0) < 0.01
    # FPPM includes both games: (60 + 0) / (30 + 30) = 1.0
    assert abs(row["FPPM"] - 1.0) < 0.01


def test_run_summary_pipeline_creates_views(summary_tables):
    mod = summary_tables
    rows = [{**BASE_ROW}]
    _seed(mod.DB_PATH, rows, [(1, "Alpha")], [("Boston Celtics", "BOS")])

    mod.run_summary_pipeline()

    from sqlalchemy import inspect
    inspector = inspect(mod.engine)
    view_names = inspector.get_view_names()
    assert "vw_player_averages_regular_season" in view_names
    assert "vw_player_averages_playoffs" in view_names
