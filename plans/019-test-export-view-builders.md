# Plan 019: Add tests for the three export view-builder scripts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat aef8efa..HEAD -- src/bigdataball/export_slate_averages_vw.py src/bigdataball/export_playoffs_slate_averages_vw.py src/bigdataball/export_slate_averages_csv.py src/bigdataball/dk_matching.py src/bigdataball/seasons.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Depends on**: none (the `dk_matching` helper and season config already exist and are tested)
- **Risk**: LOW
- **Category**: tests
- **Planned at**: commit `aef8efa`, 2026-07-24
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/59

## Why this matters

The three `export_*` scripts are the pipeline's final output stage — they build
the `vw_daily_slate`, `vw_daily_slate_l30`, and `vw_daily_slate_playoffs` views
and the slate CSVs that Excel-based DFS analysis actually consumes. Their
**view-building bodies have zero test coverage**: only the shared `dk_matching`
helper they call is tested (`docs/codebase/TESTING.md` "Gaps"). That leaves the
season-filter interpolation (`seasons.slate_seasons_sql()` / `L30_SEASON` /
`PLAYOFFS_SEASON`), the player `IN (...)` list construction, and the DROP/CREATE
view SQL untested. A regression here is exactly the kind that ships silently: a
bad `seasons.py` edit at season rollover, a renamed averages column, or a
broken IN-list would produce an empty or wrong slate view with no failing test.
This plan adds focused tests using the same env-seam pattern the rest of the
suite uses.

## Current state

The three scripts share a shape. Key facts an executor needs:

- **They resolve paths *inside* the pipeline function** (not at module level),
  via `paths.resolve_base_data_path()`, then build a local
  `engine = create_engine(f"sqlite:///{DB_PATH}")`. So a test only needs to set
  `BIGDATABALL_DATA_DIR` to a temp dir *before* calling the function — no fresh
  re-import gymnastics are required for path resolution (unlike the module-level
  engine scripts). Example (`export_slate_averages_vw.py:18-37`):

```python
def run_slate_averages_pipeline():
    BASE_DATA_PATH = paths.resolve_base_data_path()
    DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
    DK_FILE_PATH = dk_matching.find_dk_file_path()
    dk_names = dk_matching.load_dk_names(DK_FILE_PATH)
    if dk_names is None:
        return []
    ...
    engine = create_engine(f"sqlite:///{DB_PATH}")
    db_players_query = "SELECT DISTINCT PLAYER FROM vw_player_averages_regular_season"
    ...
```

- **They read from the summary views**, not raw logs:
  - `export_slate_averages_vw.py` and `export_slate_averages_csv.py` read
    `vw_player_averages_regular_season`, and filter
    `WHERE SEASON in ({seasons.slate_seasons_sql()})` (main) or
    `WHERE SEASON = '{seasons.L30_SEASON}'` (L30).
  - `export_playoffs_slate_averages_vw.py` reads
    `vw_player_averages_playoffs`, filtering `WHERE SEASON = '{seasons.PLAYOFFS_SEASON}'`.
  - All three filter `AND PLAYER IN ('{sql_names_string}')` where
    `sql_names_string = dk_matching.to_sql_in_list(matched_names)`.

- **`dk_matching.find_dk_file_path()`** returns
  `~/Downloads/DKEntries.csv` (`dk_matching.py:10-13`) — an absolute path in the
  real user home. Tests MUST NOT depend on that. Monkeypatch the export module's
  reference, e.g. `monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(my_tmp_csv))`.

- **`dk_matching.load_dk_names(path)`** reads a CSV, auto-detecting a header row
  by scanning the first 50 lines for a line containing both `"Position"` and
  `"Name + ID"`, then requires a `"Name"` column (`dk_matching.py:16-46`). A
  minimal valid DKEntries.csv the test can write:

```csv
Position,Name + ID,Name,ID
PG,Alpha Player (1),Alpha Player,1
SG,Beta Player (2),Beta Player,2
```

- **Season constants** (`seasons.py`) change annually — DO NOT hardcode
  `"2025-26"` in tests. Seed the DB using the live constants so the tests stay
  correct across rollovers: `seasons.L30_SEASON`, `seasons.SLATE_SEASONS[-1]`,
  `seasons.PLAYOFFS_SEASON`.

- **Existing test to model on**: `tests/test_create_summary_tables.py` — same
  env-seam fixture shape (`monkeypatch.setenv("BIGDATABALL_DATA_DIR", ...)`,
  fresh import, `_seed` via raw `sqlite3`, `engine.dispose()` on teardown). Read
  it before writing. `tests/test_dk_matching.py` shows the DKEntries.csv writing
  pattern.

- **Fixture/import note**: the export scripts have **no module-level engine**,
  so the fixture doesn't need to dispose one. But seed the DB and create the
  `vw_player_averages_*` views *before* calling the pipeline function. Import the
  export modules by package name (`from bigdataball import export_slate_averages_vw`).
  Because path resolution happens inside the function at call time, setting the
  env var in the fixture before the call is sufficient — but to be safe and match
  the suite, still `sys.modules.pop(...)` + `importlib.import_module(...)` the
  export module under the env var so any incidental module-level state is fresh.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install deps (editable pkg) | `pip install -e . && pip install -r requirements-dev.txt` | exit 0 |
| Run the new test file | `python -m pytest -q tests/test_export_slate_views.py` | all pass |
| Full suite | `python -m pytest -q` | `68 + N passed` (N = number of new tests) |

## Scope

**In scope** (the only files you should create/modify):
- `tests/test_export_slate_views.py` (create — covers all three export scripts)
- `plans/README.md` (status row update)

**Out of scope** (do NOT touch):
- `src/bigdataball/export_*.py`, `dk_matching.py`, `seasons.py`, any production
  code — this is a **tests-only** plan. If you find what looks like a bug in the
  export code while writing tests, do NOT fix it here; note it in your report and
  write the test to document the *current* behavior (or STOP if it blocks the
  test).
- `tests/conftest.py`, `tests/helpers.py` — add your fixture locally in the new
  test file (like `test_create_summary_tables.py` does) rather than modifying
  shared fixtures.

## Git workflow

- Branch: `advisor/019-test-export-view-builders` (or the repo's convention from
  `git log --oneline`).
- Commit message style: match `git log` (e.g. "Add tests for the export slate
  view builders").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Build the seed + fixture scaffolding

Create `tests/test_export_slate_views.py` with a fixture that points
`BIGDATABALL_DATA_DIR` at a temp dir and a `_seed_averages_views` helper that
creates a `fantasy_averages` table and the two `vw_player_averages_*` views on
top of it (mirroring what `create_summary_tables` produces in production). The
averages table needs at least these columns (used by the export queries):
`SEASON_TYPE, PLAYER, TEAM, SEASON, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM,
GSFPPM, STDV_FPPG, L30FPPM`.

```python
# tests/test_export_slate_views.py
import importlib
import os
import sqlite3
import sys

import pandas as pd
import pytest

from bigdataball import seasons


def _write_dk_csv(path, names):
    lines = ["Position,Name + ID,Name,ID"]
    for i, n in enumerate(names, start=1):
        lines.append(f"PG,{n} ({i}),{n},{i}")
    path.write_text("\n".join(lines) + "\n")


def _seed_averages_views(db_path, rows):
    """Create fantasy_averages + the two player-average views.

    rows: list of dicts with keys SEASON_TYPE, PLAYER, TEAM, SEASON, GP, GS,
    MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG, L30FPPM.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE fantasy_averages (
            SEASON_TYPE TEXT, PLAYER TEXT, TEAM TEXT, SEASON TEXT,
            GP INT, GS INT, MPG REAL, GSMPG REAL, FPPG REAL, GSFPPG REAL,
            FPPM REAL, GSFPPM REAL, STDV_FPPG REAL, L30FPPM REAL
        )
    """)
    cols = ["SEASON_TYPE","PLAYER","TEAM","SEASON","GP","GS","MPG","GSMPG",
            "FPPG","GSFPPG","FPPM","GSFPPM","STDV_FPPG","L30FPPM"]
    conn.executemany(
        f"INSERT INTO fantasy_averages ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.execute(
        "CREATE VIEW vw_player_averages_regular_season AS "
        "SELECT * FROM fantasy_averages WHERE SEASON_TYPE = 'Regular'"
    )
    conn.execute(
        "CREATE VIEW vw_player_averages_playoffs AS "
        "SELECT * FROM fantasy_averages WHERE SEASON_TYPE = 'Playoffs'"
    )
    conn.commit()
    conn.close()


def _avg_row(**over):
    base = {
        "SEASON_TYPE": "Regular", "PLAYER": "Alpha Player", "TEAM": "BOS",
        "SEASON": seasons.L30_SEASON, "GP": 10, "GS": 8, "MPG": 34.0,
        "GSMPG": 35.0, "FPPG": 45.0, "GSFPPG": 47.0, "FPPM": 1.3,
        "GSFPPM": 1.35, "STDV_FPPG": 5.0, "L30FPPM": 1.4,
    }
    base.update(over)
    return base


@pytest.fixture
def export_env(tmp_path, monkeypatch):
    """Point BIGDATABALL_DATA_DIR at a temp dir and return (db_path, tmp_path)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    db_path = str(data_dir / "nba_fantasy_logs.db")
    return db_path, tmp_path, monkeypatch
```

**Verify** the scaffolding imports cleanly (do NOT use `pytest` for this — with
no test functions yet, pytest exits with status **5** "no tests collected",
which looks like a failure):
`python -c "import ast; ast.parse(open('tests/test_export_slate_views.py').read()); print('parse OK')"` → prints `parse OK`.
Then confirm the imports resolve:
`python -c "import tests.test_export_slate_views; print('import OK')"` (run from
the repo root with the package installed) → prints `import OK`. If either errors,
fix the scaffolding before adding tests.

### Step 2: Test the regular-season view builder (`export_slate_averages_vw`)

Add tests that seed a matching regular-season row, write a DKEntries.csv whose
name fuzzy-matches the seeded PLAYER, monkeypatch `find_dk_file_path`, run
`run_slate_averages_pipeline()`, and assert the two views exist and contain the
player.

```python
def _import_fresh(mod_name):
    sys.modules.pop(mod_name, None)
    return importlib.import_module(mod_name)


def test_slate_view_created_with_matched_player(export_env):
    db_path, tmp_path, monkeypatch = export_env
    # Seed at L30_SEASON: it is in SLATE_SEASONS (== SLATE_SEASONS[-1] by the
    # seasons.py invariant), so the row appears in BOTH vw_daily_slate (filters
    # SEASON in SLATE_SEASONS) and vw_daily_slate_l30 (filters SEASON = L30_SEASON).
    # Seeding at L30_SEASON explicitly lets us assert L30 *contents* without
    # depending on that invariant holding.
    _seed_averages_views(db_path, [_avg_row(PLAYER="Alpha Player",
                                            SEASON=seasons.L30_SEASON)])
    dk_csv = tmp_path / "DKEntries.csv"
    _write_dk_csv(dk_csv, ["Alpha Player"])

    mod = _import_fresh("bigdataball.export_slate_averages_vw")
    monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(dk_csv))

    unmatched = mod.run_slate_averages_pipeline()
    assert unmatched == []

    from sqlalchemy import create_engine, inspect
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        views = inspect(engine).get_view_names()
        assert "vw_daily_slate" in views
        assert "vw_daily_slate_l30" in views
        slate = pd.read_sql_query("SELECT * FROM vw_daily_slate", engine)
        assert "Alpha Player" in slate["PLAYER"].tolist()
        # Assert L30 *contents*, not just that the view exists — a broken
        # L30_SEASON filter or a dropped L30FPPM column would still create an
        # (empty/erroring) view but fail this.
        l30 = pd.read_sql_query("SELECT * FROM vw_daily_slate_l30", engine)
        assert "Alpha Player" in l30["PLAYER"].tolist()
        assert "L30FPPM" in l30.columns
    finally:
        engine.dispose()


def test_slate_view_excludes_out_of_window_season(export_env):
    db_path, tmp_path, monkeypatch = export_env
    # Player exists but only in a season NOT in SLATE_SEASONS -> excluded.
    _seed_averages_views(db_path, [_avg_row(PLAYER="Alpha Player", SEASON="1999-00")])
    dk_csv = tmp_path / "DKEntries.csv"
    _write_dk_csv(dk_csv, ["Alpha Player"])

    mod = _import_fresh("bigdataball.export_slate_averages_vw")
    monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(dk_csv))
    mod.run_slate_averages_pipeline()

    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        slate = pd.read_sql_query("SELECT * FROM vw_daily_slate", engine)
        assert slate.empty  # season filter excluded the only row
    finally:
        engine.dispose()


def test_unmatched_dk_name_reported(export_env):
    db_path, tmp_path, monkeypatch = export_env
    _seed_averages_views(db_path, [_avg_row(PLAYER="Alpha Player",
                                            SEASON=seasons.SLATE_SEASONS[-1])])
    dk_csv = tmp_path / "DKEntries.csv"
    _write_dk_csv(dk_csv, ["Zzzzz Nomatch"])  # nothing close in the DB

    mod = _import_fresh("bigdataball.export_slate_averages_vw")
    monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(dk_csv))
    unmatched = mod.run_slate_averages_pipeline()
    assert any("Zzzzz Nomatch" in u for u in unmatched)
```

**Verify**: `python -m pytest -q tests/test_export_slate_views.py` → `3 passed`.

If `test_slate_view_created_with_matched_player` fails because `unmatched` is not
empty, the fuzzy threshold (≥90) didn't match the identical name — check the DK
CSV writer produced an exact `Name` value equal to the seeded PLAYER.

### Step 3: Test the playoffs view builder (`export_playoffs_slate_averages_vw`)

```python
def test_playoffs_view_created(export_env):
    db_path, tmp_path, monkeypatch = export_env
    _seed_averages_views(db_path, [
        _avg_row(SEASON_TYPE="Playoffs", PLAYER="Alpha Player",
                 SEASON=seasons.PLAYOFFS_SEASON),
    ])
    dk_csv = tmp_path / "DKEntries.csv"
    _write_dk_csv(dk_csv, ["Alpha Player"])

    mod = _import_fresh("bigdataball.export_playoffs_slate_averages_vw")
    monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(dk_csv))
    unmatched = mod.run_playoffs_slate_averages_pipeline()
    assert unmatched == []

    from sqlalchemy import create_engine, inspect
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert "vw_daily_slate_playoffs" in inspect(engine).get_view_names()
        df = pd.read_sql_query("SELECT * FROM vw_daily_slate_playoffs", engine)
        assert "Alpha Player" in df["PLAYER"].tolist()
    finally:
        engine.dispose()
```

**Verify**: `python -m pytest -q tests/test_export_slate_views.py -k playoffs` → `1 passed`.

### Step 4: Test the CSV exporter (`export_slate_averages_csv`)

This one writes timestamped CSVs into `<data>/csv_exports/` rather than views.
Assert the main and L30 CSVs are written and contain the matched player.

```python
def test_csv_export_writes_files(export_env):
    db_path, tmp_path, monkeypatch = export_env
    # Seed at L30_SEASON (in SLATE_SEASONS by the seasons.py invariant) so the
    # row lands in both the main and L30 CSVs and we can assert L30 contents.
    _seed_averages_views(db_path, [_avg_row(PLAYER="Alpha Player",
                                            SEASON=seasons.L30_SEASON)])
    dk_csv = tmp_path / "DKEntries.csv"
    _write_dk_csv(dk_csv, ["Alpha Player"])

    mod = _import_fresh("bigdataball.export_slate_averages_csv")
    monkeypatch.setattr(mod.dk_matching, "find_dk_file_path", lambda: str(dk_csv))
    mod.run_slate_averages_smart_export()

    export_dir = os.path.join(os.path.dirname(db_path), "csv_exports")
    files = os.listdir(export_dir)
    main_files = [f for f in files if f.startswith("slate_player_averages_") and "_l30_" not in f]
    l30_files = [f for f in files if f.startswith("slate_player_averages_l30_")]
    assert main_files, f"no main CSV written; dir had {files}"
    assert l30_files, f"no L30 CSV written; dir had {files}"

    main_df = pd.read_csv(os.path.join(export_dir, main_files[0]))
    assert "Alpha Player" in main_df["PLAYER"].tolist()
    # Assert L30 CSV contents too, not just that the file exists.
    l30_df = pd.read_csv(os.path.join(export_dir, l30_files[0]))
    assert "Alpha Player" in l30_df["PLAYER"].tolist()
```

**Verify**: `python -m pytest -q tests/test_export_slate_views.py -k csv` → `1 passed`.

### Step 5: Run the whole new file and the full suite

**Verify**:
- `python -m pytest -q tests/test_export_slate_views.py` → `5 passed` (3 + 1 + 1).
- `python -m pytest -q` → `73 passed` (68 existing + 5 new).

If the total isn't 73, reconcile the count before updating the index.

### Step 6: Update the plans index

`plans/README.md` already has a `TODO` row for plan 019 — **update that existing
row in place** to DONE (do NOT add a second 019 row) with the new file name and
test count, matching the neighboring rows' formatting. Update
`docs/codebase/TESTING.md`'s "Gaps" section only if the reviewer asks — that doc
edit is out of scope for this tests-only plan unless requested.

## Test plan

- New file `tests/test_export_slate_views.py`, 5 tests:
  - `test_slate_view_created_with_matched_player` — happy path: matched DK name →
    `vw_daily_slate` + `vw_daily_slate_l30` created and contain the player.
  - `test_slate_view_excludes_out_of_window_season` — the season filter actually
    excludes a player whose only row is outside `SLATE_SEASONS`.
  - `test_unmatched_dk_name_reported` — an unmatchable DK name is returned in the
    `unmatched_names` list (the value the orchestrator uses for its email
    warning / `todo_mappings.txt` worklist).
  - `test_playoffs_view_created` — `vw_daily_slate_playoffs` built from the
    playoffs view + `PLAYOFFS_SEASON` filter.
  - `test_csv_export_writes_files` — main + L30 timestamped CSVs written with the
    matched player.
- Structural pattern: `tests/test_create_summary_tables.py` (env-seam fixture,
  raw-`sqlite3` seeding) + `tests/test_dk_matching.py` (DKEntries.csv shape).
- Verification: `python -m pytest -q` → all pass, including the 5 new tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tests/test_export_slate_views.py` exists with 5 tests
- [ ] `python -m pytest -q tests/test_export_slate_views.py` → `5 passed`
- [ ] `python -m pytest -q` → `73 passed`
- [ ] `git status --short` shows only `tests/test_export_slate_views.py` and `plans/README.md` (NO `src/` changes — this is tests-only)
- [ ] `plans/README.md` status row for 019 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Any export script's "Current state" excerpt doesn't match the live code
  (drift — the queries, view names, or season-filter calls changed).
- A test can only pass by editing production code — that means either a real bug
  or a wrong test assumption; report it rather than touching `src/`.
- `dk_matching.find_dk_file_path` can't be monkeypatched via the export module's
  `.dk_matching` attribute (import structure changed) — report the new structure
  instead of reaching into the real `~/Downloads`.
- The full suite is not `68 passed` before your changes (baseline drift).

## Maintenance notes

- These tests seed `fantasy_averages` + the two `vw_player_averages_*` views
  directly rather than running `create_summary_tables`, to isolate the export
  logic. If the averages schema changes (a column added/renamed), update
  `_seed_averages_views`'s column list to match, or the export queries will fail
  in-test the same way they would in production (which is the point).
- The tests reference `seasons.*` constants rather than literals, so they survive
  the annual `seasons.py` rollover. A reviewer should confirm no test hardcodes a
  season string except the deliberately-out-of-window `"1999-00"` case.
- `run_slate_averages_pipeline` swallows its inner exceptions and prints them
  (it only returns `unmatched_names`), so a broken view CREATE won't raise — the
  tests assert on the *resulting view/CSV state*, not on exceptions, which is why
  they query the DB after the call.
