# Plan 011: Add tests for `create_summary_tables.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3844392..HEAD -- create_summary_tables.py tests/conftest.py`
> Compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: LOW
- **Depends on**: none (uses the same env-seam pattern as existing fixtures)
- **Category**: tests
- **Planned at**: commit `3844392`, 2026-06-21
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/29

## Why this matters

`create_summary_tables.py` is the aggregation core of the pipeline — it reads all
fantasy logs, joins with player/team dimensions, computes per-player season averages
(FPPG, MPG, FPPM, L30FPPM, GS stats), and writes `fantasy_averages` plus two
convenience views. It is 414 lines with zero test coverage. A bug here silently
produces wrong averages that flow into every slate export and the Excel DFS analysis.
`docs/codebase/TESTING.md` explicitly flags this as a near-term goal. The env-seam
fixture pattern from the existing test suite applies directly.

## Current state

**Zero tests exist for this module.** The only test file that exercises aggregation
indirectly is `test_orchestrator_warnings.py`, which stubs out `run_summary_pipeline`.

**`create_summary_tables.py`** — key behaviors to test:

Module-level path resolution (lines 9-23):
```python
# create_summary_tables.py:9-23
BASE_DATA_PATH = paths.resolve_base_data_path()
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
...
engine = create_engine(f"sqlite:///{DB_PATH}")
```

Required tables guard (lines 34-52):
```python
required_tables = [LOGS_TABLE_NAME, MAP_TEAMS_TABLE_NAME, DIM_PLAYERS_TABLE_NAME]
...
if missing_tables:
    print(f"\n*** ERROR: Missing required tables: ... ***")
    return False
```

SEASON_TYPE classification via `np.select` (lines 85-90):
```python
conditions = [
    df["SEASON_SEGMENT"].str.contains("Regular Season|In-Season Tournament"),
    df["SEASON_SEGMENT"].str.contains("Playoffs|Play-In"),
]
choices = ["Regular", "Playoffs"]
df["SEASON_TYPE"] = np.select(conditions, choices, default=None)
```

SEASON_KEY derivation for regular season (lines 95-118):
```python
start_year_series = df.loc[reg_season_mask, "SEASON_SEGMENT"].str.extract(r"(\d{4})", expand=False)
...
df.loc[reg_season_mask, "SEASON_KEY"] = (start_year_series + "-" + end_year_series)
```
A `SEASON_SEGMENT` of `"2024-25 NBA Regular Season"` → `SEASON_KEY = "2024-25"`.

L30FPPM calculation (lines 131-138, 202-207):
```python
thirty_days_ago = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
df["L30_DK_POINTS"] = np.where(df["DATE"] >= thirty_days_ago, df["DK_POINTS"], np.nan)
df["L30_MINUTES"] = np.where(df["DATE"] >= thirty_days_ago, df["MINUTES"], np.nan)
...
grouped["L30FPPM"] = (grouped["L30_DK_POINTS_sum"] / grouped["L30_MINUTES_sum"])...
```
Players with all games older than 30 days → `L30FPPM = 0`.

Player dimension join (lines 62-70): the `PLAYER` column in `fantasy_logs` is DROPPED
and replaced with the canonical name from `dim_players.PLAYER_NAME`:
```python
df.drop(columns=["PLAYER"], inplace=True)
df = pd.merge(df, dim_players_df[["PLAYER_ID", "PLAYER_NAME"]], on="PLAYER_ID", how="left")
df.rename(columns={"PLAYER_NAME": "PLAYER"}, inplace=True)
```

Team abbreviation join (lines 72-80): `fantasy_logs.TEAM` is joined to
`map_teams.RAW_TEAM_NAME` to produce `TEAM_ABBREVIATION`.

Entry point: `run_summary_pipeline()` (lines 404-409):
```python
def run_summary_pipeline():
    if create_fantasy_averages_table():
        successful_views = create_convenience_views()
        export_views_to_csv(successful_views)
```
Returns `None`. `create_fantasy_averages_table()` returns `True` on success, `False`
on missing tables or exception.

**Minimum columns needed in `fantasy_logs`** for the aggregation to succeed:
`PLAYER_ID`, `PLAYER`, `DATE`, `SEASON_SEGMENT`, `TEAM`, `DK_POINTS`, `DK_SALARY`,
`MINUTES`, `STARTED`, `USAGE`.
Other columns present in production data (OPPONENT, VENUE, etc.) are passthrough — their
absence does not affect aggregation.

**Existing env-seam fixture pattern** (from `tests/conftest.py:67-87`,
`player_upload` fixture):
```python
@pytest.fixture
def player_upload(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Player_Logs").mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    sys.modules.pop("daily_player_upload", None)
    module = importlib.import_module("daily_player_upload")
    yield module
    module.engine.dispose()
    sys.modules.pop("daily_player_upload", None)
```
The `summary_tables` fixture follows the same structure but imports
`create_summary_tables` and disposes `module.engine`.

## Commands you will need

| Purpose       | Command                                                    | Expected on success |
|---------------|------------------------------------------------------------|---------------------|
| Syntax check  | `python3 -m py_compile tests/test_create_summary_tables.py` | exit 0             |
| Run new tests | `python3 -m pytest -q tests/test_create_summary_tables.py` | all pass           |
| Full suite    | `python3 -m pytest -q`                                     | all pass            |

## Scope

**In scope** (the only files you should create or modify):
- `tests/test_create_summary_tables.py` (create)

**Out of scope** (do NOT touch):
- `create_summary_tables.py` — production code must not change
- `tests/conftest.py` — add the `summary_tables` fixture directly in the new test file
  (self-contained, no need to pollute conftest)
- Any other source module

## Git workflow

- Branch: `advisor/011-summary-tables-tests` or current branch if instructed.
- One commit; message: `Add tests for create_summary_tables aggregation (plan 011)`.
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Create `tests/test_create_summary_tables.py` with the fixture

The fixture seeds the three required tables in a temp DB and imports
`create_summary_tables` with `BIGDATABALL_DATA_DIR` set to the temp path.

```python
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
```

**Verify**: `python3 -m py_compile tests/test_create_summary_tables.py` → exit 0.

### Step 2: Add `test_missing_tables_returns_false`

Verifies the guard at `create_summary_tables.py:34-52`:

```python
def test_missing_tables_returns_false(summary_tables):
    mod = summary_tables
    # DB exists but none of the required tables are created.
    result = mod.create_fantasy_averages_table()
    assert result is False
```

**Verify**: `python3 -m pytest -q tests/test_create_summary_tables.py::test_missing_tables_returns_false` → 1 passed.

### Step 3: Add `test_basic_aggregation_creates_fantasy_averages`

Seeds a single player with two regular-season games and verifies:
- `fantasy_averages` table exists with 1 row
- `GP = 2`, `FPPG` = average of the two DK_POINTS scores
- `SEASON = "2024-25"`, `TEAM = "BOS"`
- Canonical player name from `dim_players` (not the raw `PLAYER` from `fantasy_logs`)

```python
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
```

**Verify**: `python3 -m pytest -q tests/test_create_summary_tables.py::test_basic_aggregation_creates_fantasy_averages` → 1 passed.

### Step 4: Add `test_season_type_classification`

Verifies that Regular Season and Playoffs rows are classified correctly and produce
separate rows in `fantasy_averages` (different `SEASON_TYPE`):

```python
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
```

**Verify**: `python3 -m pytest -q tests/test_create_summary_tables.py::test_season_type_classification` → 1 passed.

### Step 5: Add `test_l30fppm_excludes_old_games`

Verifies that `L30FPPM` is computed from only the last 30 days of data. Seeds two
games: one within the last 30 days (high score) and one outside (low score). L30FPPM
should reflect only the recent game.

```python
def test_l30fppm_excludes_old_games(summary_tables):
    mod = summary_tables
    import pandas as pd
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
```

**Verify**: `python3 -m pytest -q tests/test_create_summary_tables.py::test_l30fppm_excludes_old_games` → 1 passed.

### Step 6: Add `test_run_summary_pipeline_creates_views`

Verifies the public entry point `run_summary_pipeline()` creates `vw_player_averages_regular_season`
and `vw_player_averages_playoffs` views:

```python
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
```

**Verify**: `python3 -m pytest -q tests/test_create_summary_tables.py::test_run_summary_pipeline_creates_views` → 1 passed.

### Step 7: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass (existing + 5 new).

## Test plan

New file `tests/test_create_summary_tables.py` with 5 tests:

1. `test_missing_tables_returns_false` — guard at entry: missing source tables → False.
2. `test_basic_aggregation_creates_fantasy_averages` — GP, FPPG, SEASON, TEAM, canonical PLAYER.
3. `test_season_type_classification` — Regular vs. Playoffs SEASON_TYPE and SEASON_KEY format.
4. `test_l30fppm_excludes_old_games` — L30FPPM uses only the last 30 days; FPPM uses all.
5. `test_run_summary_pipeline_creates_views` — public entry point creates convenience views.

Pattern: same env-seam approach as `tests/test_daily_player_upload.py` — fresh import
under `BIGDATABALL_DATA_DIR`, `engine.dispose()` on teardown, real SQLite under `tmp_path`.
The `_seed` helper uses `sqlite3` directly (same style as `test_check_ingest_duplicates.py`).

## Done criteria

ALL must hold:

- [ ] `python3 -m py_compile tests/test_create_summary_tables.py` exits 0
- [ ] `python3 -m pytest -q tests/test_create_summary_tables.py` exits 0 with exactly 5 tests
- [ ] `python3 -m pytest -q` exits 0 — full suite still passes
- [ ] `git diff --name-only` shows only `tests/test_create_summary_tables.py`
- [ ] `plans/README.md` status row for 011 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `create_summary_tables.py` has no module-level `engine` attribute — the env-seam fixture relies on it for disposal (`module.engine.dispose()`).
- The `SEASON_SEGMENT` strings in the tests don't produce the expected `SEASON_TYPE` classification — the `str.contains` patterns in `create_summary_tables.py:86-88` may have changed.
- Step 3's `FPPG` assertion fails (mean is wrong) — check whether `rounding_map` has changed; the test compares with 0.01 tolerance to accommodate rounding.
- Any step's verification fails twice after a reasonable fix attempt.
- The `MINUTES` column is not found in `fantasy_logs` during aggregation — the fantasy log Excel format may not include minutes; report back with the actual column names present.

## Maintenance notes

- The `_seed` function hardcodes the minimum column set for `fantasy_logs`. If new columns are added to the aggregation in `create_summary_tables.py` (and those columns become non-nullable in the aggregation logic), update `_seed` and `BASE_ROW` accordingly.
- If `SEASON_SEGMENT` format from BigDataBall changes (e.g. "2024-25 Regular Season" without "NBA"), update the test `REGULAR_SEGMENT` / `PLAYOFF_SEGMENT` constants and the `str.contains` patterns in `create_summary_tables.py`.
- `test_l30fppm_excludes_old_games` uses `pd.Timestamp.now()` — it is inherently time-coupled. The dates computed from "today" ensure the test passes on any run date, but if the test starts failing seasonally it's likely a timezone issue (`normalize()` gives midnight local time; CI runs UTC).
- A reviewer should confirm `test_basic_aggregation_creates_fantasy_averages` produces the same `TEAM` value (`"BOS"`) that appears in `map_teams` — the join is left-outer, so a mismatch in `RAW_TEAM_NAME` would give `NULL`/`None`, not `"BOS"`.
