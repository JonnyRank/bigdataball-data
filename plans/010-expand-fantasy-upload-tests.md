# Plan 010: Expand the fantasy log upload test suite

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3844392..HEAD -- tests/test_daily_fantasy_log_upload.py tests/helpers.py tests/conftest.py daily_fantasy_log_upload.py`
> Compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (fixture and helpers already exist)
- **Category**: tests
- **Planned at**: commit `3844392`, 2026-06-21
- **Issue**: <!-- filled in after GitHub issue is created -->

## Why this matters

`daily_fantasy_log_upload.py` is the pipeline's other ingestion path (DFS fantasy
logs). It's a high-churn file (~2 entries in the last 90 days) that handles column
sanitization, name standardization, column drops/renames, date formatting, and player
dimension learning. Currently only the cross-file dedup regression is covered
(`test_dedup_across_files_in_one_run` in `tests/test_daily_fantasy_log_upload.py`).
Name standardization, column-drop behavior, date formatting, and player learning are
untested. Adding these tests brings the fantasy upload to parity with the player upload
test suite and catches regressions introduced by future format changes.

## Current state

**`tests/test_daily_fantasy_log_upload.py`** (1 test today):
```python
# tests/test_daily_fantasy_log_upload.py
import os
from tests.helpers import write_fantasy_xlsx, make_fantasy_rows, count_rows

def test_dedup_across_files_in_one_run(fantasy_upload):
    ...
```

**`tests/helpers.py`** — helper functions that already exist:
```python
# tests/helpers.py:15-42

def write_fantasy_xlsx(path, rows):
    """Write a fantasy log .xlsx matching daily_fantasy_log_upload's read format.

    daily_fantasy_log_upload reads with header=1 (column names on xlsx row 1) then
    skips the first DataFrame row via iloc[1:].  So this helper writes:
      xlsx row 0: empty  (before the header — ignored by pandas)
      xlsx row 1: column names  (header=1 target)
      xlsx row 2: dummy row     (consumed by iloc[1:] and discarded)
      xlsx row 3+: actual data
    """
    cols = ["PLAYER_ID", "PLAYER", "DATE"]
    dummy = {c: None for c in cols}
    df = pd.DataFrame([dummy] + list(rows), columns=cols)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=1)

def make_fantasy_rows(specs):
    """specs: list of (player_id, player_name, date) tuples."""
    return [{"PLAYER_ID": pid, "PLAYER": name, "DATE": date} for pid, name, date in specs]
```

Note: `write_fantasy_xlsx` writes a fixed 3-column layout. To test column-drop or
rename behavior, rows can include additional keys; the helper needs a minor extension
to support a custom `cols` list — see Step 2.

**`tests/conftest.py`** — `fantasy_upload` fixture (already present at lines 32-64):
```python
@pytest.fixture
def fantasy_upload(tmp_path, monkeypatch):
    """Imports daily_fantasy_log_upload fresh with BASE_DATA_PATH pointed at a temp dir."""
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Fantasy_Logs").mkdir(parents=True)
    ...
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    ...
    module = importlib.import_module("daily_fantasy_log_upload")
    yield module
    module.engine.dispose()
    ...
```

**`daily_fantasy_log_upload.py`** — behaviors being tested:

Name standardization (lines 192-202):
```python
if "PLAYER" in cleaned_data.columns:
    changed_mask = cleaned_data["PLAYER"].isin(mappings.PLAYER_NAME_MAP)
    ...
    cleaned_data["PLAYER"] = cleaned_data["PLAYER"].replace(mappings.PLAYER_NAME_MAP)
```

Column drops (lines 160-167):
```python
columns_to_drop = [
    "FANDUEL", "YAHOO", "FOR_FANDUEL_FULL_ROSTER_CONTESTS",
    "FOR_YAHOO_FULL_SLATE_CONTESTS", "FANDUEL1", "YAHOO1",
]
```

Date formatting (lines 181-183):
```python
cleaned_data["DATE"] = pd.to_datetime(cleaned_data["DATE"]).dt.strftime("%Y-%m-%d")
```

Rename map (lines 168-179) — key renames:
```python
rename_map = {
    "BIGDATABALL_DATASET": "SEASON_SEGMENT",
    ...
    "FOR_DRAFTKINGS_CLASSIC_CONTESTS": "DK_SALARY",
    "DRAFTKINGS1": "DK_POINTS",
}
```

Player learning (lines 220-243): when `truly_new_logs_df` contains a PLAYER_ID not
already in `dim_players`, that player is inserted.

**Known name mapping (from `mappings.py`)**: `"GG Jackson"` → `"Gregory Jackson"`.
Use this in the standardization test (same convention as `test_player_name_standardization_applied`
in `tests/test_daily_player_upload.py:24-33`).

**Repo test conventions:**
- Use the `fantasy_upload` fixture; never mock the DB.
- `count_rows(mod.engine, "<table>")` counts rows in a table.
- `pd.read_sql_query("SELECT col FROM table", mod.engine)["col"].tolist()` reads values.
- Model new tests after the structure of `tests/test_daily_player_upload.py`.

## Commands you will need

| Purpose    | Command                                          | Expected on success |
|------------|--------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile tests/test_daily_fantasy_log_upload.py tests/helpers.py` | exit 0 |
| Run new tests | `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py` | all pass |
| Full suite | `python3 -m pytest -q`                           | all pass            |

## Scope

**In scope** (the only files you should modify):
- `tests/test_daily_fantasy_log_upload.py` — add 4 new tests
- `tests/helpers.py` — extend `write_fantasy_xlsx` to accept a custom `cols` parameter

**Out of scope** (do NOT touch):
- `daily_fantasy_log_upload.py` — production code must not change
- `tests/conftest.py` — the `fantasy_upload` fixture is already correct
- Any other test file or source module

## Git workflow

- Branch: `advisor/010-fantasy-upload-tests` or the current branch if instructed.
- One commit; message style matches repo: `Add fantasy log upload test suite (plan 010)`.
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Extend `write_fantasy_xlsx` to support custom column sets

`tests/helpers.py` currently hardcodes `cols = ["PLAYER_ID", "PLAYER", "DATE"]`.
Add a `cols` keyword argument so tests can pass rows with extra columns (e.g. FANDUEL,
DRAFTKINGS1) without modifying existing callers.

Change `write_fantasy_xlsx` from:
```python
def write_fantasy_xlsx(path, rows):
    cols = ["PLAYER_ID", "PLAYER", "DATE"]
    dummy = {c: None for c in cols}
    df = pd.DataFrame([dummy] + list(rows), columns=cols)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=1)
```

To:
```python
def write_fantasy_xlsx(path, rows, cols=None):
    if cols is None:
        cols = ["PLAYER_ID", "PLAYER", "DATE"]
    dummy = {c: None for c in cols}
    df = pd.DataFrame([dummy] + list(rows), columns=cols)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=1)
```

**Verify**: `python3 -m py_compile tests/helpers.py` → exit 0.

### Step 2: Add `test_single_file_loads_logs_and_learns_players`

This mirrors the first test in `test_daily_player_upload.py`. Write the test in
`tests/test_daily_fantasy_log_upload.py` (add after the existing dedup test):

```python
import pandas as pd

def test_single_file_loads_logs_and_learns_players(fantasy_upload):
    mod = fantasy_upload
    rows = make_fantasy_rows([
        (1, "Alpha Player", "2025-11-01"),
        (2, "Beta Player", "2025-11-01"),
        (1, "Alpha Player", "2025-11-02"),
    ])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    assert count_rows(mod.engine, "fantasy_logs") == 3
    assert count_rows(mod.engine, "dim_players") == 2
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_single_file_loads_logs_and_learns_players` → 1 passed.

### Step 3: Add `test_player_name_standardization_applied`

Uses the `"GG Jackson"` → `"Gregory Jackson"` mapping from `mappings.PLAYER_NAME_MAP`:

```python
def test_player_name_standardization_applied(fantasy_upload):
    mod = fantasy_upload
    rows = make_fantasy_rows([(10, "GG Jackson", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    names = pd.read_sql_query("SELECT PLAYER FROM fantasy_logs", mod.engine)["PLAYER"].tolist()
    assert names == ["Gregory Jackson"]
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_player_name_standardization_applied` → 1 passed.

### Step 4: Add `test_unwanted_columns_are_dropped`

The script drops `["FANDUEL", "YAHOO", ...]` from the source file. Verify they don't
land in `fantasy_logs`. Also verifies the rename of `"DRAFTKINGS1"` → `"DK_POINTS"`.

```python
def test_unwanted_columns_are_dropped(fantasy_upload):
    mod = fantasy_upload
    extra_cols = ["PLAYER_ID", "PLAYER", "DATE", "FANDUEL", "DRAFTKINGS1"]
    rows = [{"PLAYER_ID": 1, "PLAYER": "Alpha", "DATE": "2025-11-01", "FANDUEL": 30.5, "DRAFTKINGS1": 45.2}]
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows, cols=extra_cols)

    mod.main()

    import sqlalchemy
    with mod.engine.connect() as conn:
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(fantasy_logs)"))
        col_names = [row[1] for row in result]
    assert "FANDUEL" not in col_names
    assert "DK_POINTS" in col_names
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_unwanted_columns_are_dropped` → 1 passed.

### Step 5: Add `test_date_stored_as_iso_format`

Confirms dates are stored as `"YYYY-MM-DD"` strings regardless of input format:

```python
def test_date_stored_as_iso_format(fantasy_upload):
    mod = fantasy_upload
    rows = make_fantasy_rows([(1, "Alpha", "11/01/2025")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    dates = pd.read_sql_query("SELECT DATE FROM fantasy_logs", mod.engine)["DATE"].tolist()
    assert dates == ["2025-11-01"]
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_date_stored_as_iso_format` → 1 passed.

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass (existing + 4 new = net +4 tests in this file).

## Test plan

New tests added to `tests/test_daily_fantasy_log_upload.py`:

1. `test_single_file_loads_logs_and_learns_players` — happy path: correct row count in `fantasy_logs`, correct player count in `dim_players`.
2. `test_player_name_standardization_applied` — `mappings.PLAYER_NAME_MAP` is applied before insert.
3. `test_unwanted_columns_are_dropped` — `FANDUEL` absent, `DK_POINTS` (renamed from `DRAFTKINGS1`) present in table schema.
4. `test_date_stored_as_iso_format` — dates normalized to `YYYY-MM-DD` regardless of source format.

Model after the structural pattern of `tests/test_daily_player_upload.py` (env-seam fixture, no DB mocking, real SQLite under `tmp_path`).

## Done criteria

ALL must hold:

- [ ] `python3 -m py_compile tests/test_daily_fantasy_log_upload.py tests/helpers.py` exits 0
- [ ] `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py` exits 0 with 5 tests (1 original + 4 new)
- [ ] `python3 -m pytest -q` exits 0 — full suite still passes
- [ ] `git diff --name-only` shows only `tests/test_daily_fantasy_log_upload.py` and `tests/helpers.py`
- [ ] `plans/README.md` status row for 010 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `fantasy_upload` fixture doesn't exist in `tests/conftest.py` at the expected location — the fixture is a prerequisite for all new tests.
- The `write_fantasy_xlsx` function signature has changed since this plan was written (drift check).
- `"GG Jackson"` is no longer in `mappings.PLAYER_NAME_MAP` — use a different mapping that is present, and note it.
- Any new test raises a `KeyError` for a column that the production code expects — the production code has likely changed; treat as a STOP condition.
- Step 6 verification shows a regression in any previously-passing test.

## Maintenance notes

- The 4 tests use the same `fantasy_upload` fixture as `test_orchestrator_warnings.py` — if the fixture is changed (e.g. to add stub modules), re-run this file's tests to confirm they still pass.
- If the `daily_fantasy_log_upload.py` column-drop list (`columns_to_drop`) is extended, update `test_unwanted_columns_are_dropped` to cover the new column.
- If `mappings.PLAYER_NAME_MAP` grows, no change to tests is needed — the `"GG Jackson"` → `"Gregory Jackson"` mapping is stable.
