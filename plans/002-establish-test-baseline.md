# Plan 002: Establish a pytest verification baseline with an integration harness for the upload scripts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- daily_player_upload.py daily_fantasy_log_upload.py`
> If either file changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: 001 (so `pip install` works; not strictly required but recommended)
- **Category**: tests
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

The repo has **zero automated tests** and no way to know a change is safe. Two
data-integrity bugs (planned separately in 003 and 004) currently ship silently
because nothing exercises the ingestion path. This plan creates the first
verification baseline: a `pytest` setup plus an integration harness that runs an
upload script's `main()` against a **temporary SQLite database in a temp directory**,
so the bug-fix plans that follow can add regression tests. It also adds one small,
backward-compatible seam — an optional `BIGDATABALL_DATA_DIR` environment variable —
that lets tests redirect the scripts' data directory without otherwise changing
behavior.

## Current state

Both upload scripts resolve their data directory at **module import time** and bind
the SQLAlchemy engine to it immediately:

- `daily_player_upload.py:16-38` — the path block and engine:
```python
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
NEW_FILES_FOLDER = os.path.join(BASE_DATA_PATH, "Daily_Player_Logs")
PROCESSED_FOLDER = os.path.join(BASE_DATA_PATH, "Archived_Player_Logs")
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
...
engine = create_engine(f"sqlite:///{DB_PATH}")
```
- `daily_fantasy_log_upload.py:24-46` — the same block with `Daily_Fantasy_Logs` /
  `Archived_Fantasy_Logs` and `LOGS_TABLE_NAME = "fantasy_logs"`.

Because these are module-level, a test must set the env var **before importing the
module**, then import it fresh. The fixture in this plan does exactly that.

`daily_player_upload.main()` behavior (the simpler of the two — used for the harness):
- Reads every `*.xlsx` in `NEW_FILES_FOLDER` with `pd.read_excel(path)` (header row 0).
- Sanitizes column names (upper-case, spaces/newlines/hyphens → `_`, strip non-alphanumerics),
  applies `rename_map`, formats `DATE` to `YYYY-MM-DD`, standardizes player names via
  `mappings.PLAYER_NAME_MAP`.
- Builds `log_key = PLAYER_ID + "_" + DATE`, skips keys already in `player_logs`,
  inserts new rows into `player_logs`, learns new `PLAYER_ID`s into `dim_players`.
- Moves each processed file to `Archived_Player_Logs` via `os.replace`.
- Returns `(processed_count, overwritten_count)`.

`mappings.PLAYER_NAME_MAP` (relevant for a test assertion) includes
`"GG Jackson": "Gregory Jackson"`.

Environment: Python 3.11; `pandas`, `openpyxl`, `SQLAlchemy` are in `requirements.txt`.
`G:\My Drive` does not exist on Linux/CI, so today the scripts already fall back to
`<repo>/Data`. This plan does **not** rely on that fallback for tests — it uses the
new env var to point at a temp dir instead, so tests never touch `<repo>/Data`.

## Commands you will need

| Purpose        | Command                                                        | Expected on success            |
|----------------|----------------------------------------------------------------|--------------------------------|
| Install deps   | `python3 -m pip install -r requirements.txt`                   | exit 0                         |
| Install test deps | `python3 -m pip install -r requirements-dev.txt`           | exit 0 (`pytest` installed)    |
| Run tests      | `python3 -m pytest -q`                                          | all pass, ≥3 tests             |
| Syntax check   | `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` | exit 0     |

If `pip install` cannot reach the network in your environment, STOP and report — the
tests need `pandas`/`pytest` installed.

## Scope

**In scope** (the only files you should create or modify):
- `daily_player_upload.py` — add the `BIGDATABALL_DATA_DIR` env override (Step 2 only).
- `daily_fantasy_log_upload.py` — add the same env override (Step 2 only).
- `requirements-dev.txt` (create)
- `pytest.ini` (create)
- `tests/__init__.py` (create, empty)
- `tests/conftest.py` (create)
- `tests/helpers.py` (create)
- `tests/test_daily_player_upload.py` (create)

**Out of scope** (do NOT touch, even though they look related):
- The dedup loop logic in either upload script — that is fixed in plan 003. This plan
  only adds the env seam and tests that capture *current* correct behavior.
- `daily_fantasy_log_upload.py`'s `unmatched_dk_players` handling — fixed in plan 004.
- `create_summary_tables.py`, the export scripts, `config.py` — later plans own those.
- Do not change the `G:\My Drive` branch or the `<repo>/Data` fallback; only *prepend*
  the new env-var branch.

## Git workflow

- Branch: current branch (`claude/improve-hgtf9i`) unless instructed otherwise.
- Commit the env-seam change and the test scaffolding together; message e.g.
  `Add pytest baseline and integration harness for upload scripts`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create the dev requirements and pytest config

Create `requirements-dev.txt`:
```
pytest>=7.4
```

Create `pytest.ini`:
```
[pytest]
pythonpath = .
testpaths = tests
```

**Verify**: `python3 -m pip install -r requirements-dev.txt` → exit 0;
`python3 -c "import pytest"` → exit 0.

### Step 2: Add the `BIGDATABALL_DATA_DIR` env override to both upload scripts

In **`daily_player_upload.py`**, replace the path-resolution block (currently lines
~19-24) so the env var takes precedence, leaving the existing two branches intact:

```python
# HARDCODED PATHS FOR MIGRATION
# An explicit override (used by tests and for local runs) wins; otherwise
# use the Google Drive (G:) mount, else fall back to a local Data/ folder.
if os.environ.get("BIGDATABALL_DATA_DIR"):
    BASE_DATA_PATH = os.environ["BIGDATABALL_DATA_DIR"]
elif os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    # Fallback for non-synced machines
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
```

Make the **identical** change in **`daily_fantasy_log_upload.py`** (its block is at
lines ~28-32, with the same two existing branches). Do not change anything else in
either file — the `NEW_FILES_FOLDER` / `PROCESSED_FOLDER` / `DB_PATH` / `engine`
lines below the block stay exactly as they are.

**Verify**:
- `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` → exit 0.
- `BIGDATABALL_DATA_DIR=/tmp/bdb_seam_check python3 -c "import daily_player_upload as m; print(m.BASE_DATA_PATH)"`
  → prints `/tmp/bdb_seam_check`.
- `python3 -c "import daily_player_upload as m; print('Data' in m.BASE_DATA_PATH or 'My Drive' in m.BASE_DATA_PATH)"`
  (no env var) → prints `True` (the fallback still works).

### Step 3: Create the test helpers

Create `tests/__init__.py` (empty file).

Create `tests/helpers.py` — builds a minimal valid player-feed `.xlsx`. The columns
are named so that, after the script's sanitization (upper-case, spaces→`_`), they
already match the names the script expects (`PLAYER_ID`, `PLAYER`, `DATE`); the
`rename_map` leaves them untouched because none of its keys are present:

```python
import pandas as pd


def write_player_xlsx(path, rows):
    """rows: list of dicts with keys PLAYER_ID, PLAYER, DATE (and optional stats).
    Writes an .xlsx with header on row 0, matching daily_player_upload's read_excel."""
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER", "DATE", "PTS"])
    df.to_excel(path, index=False)


def make_rows(specs):
    """specs: list of (player_id, player_name, date, pts) tuples."""
    return [
        {"PLAYER_ID": pid, "PLAYER": name, "DATE": date, "PTS": pts}
        for pid, name, date, pts in specs
    ]
```

**Verify**: `python3 -c "import tests.helpers"` from the repo root → exit 0.

### Step 4: Create the fixture that runs the player upload against a temp data dir

Create `tests/conftest.py`:

```python
import importlib
import os
import sys

import pytest


@pytest.fixture
def player_upload(tmp_path, monkeypatch):
    """Imports daily_player_upload fresh with BASE_DATA_PATH pointed at a temp dir.
    Returns the imported module; its `engine`, paths, and tables all live under tmp_path."""
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Player_Logs").mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

    # Force a fresh import so the module-level path/engine code re-runs with the env var.
    # (pop + import_module already yields a fresh import that reads the env var; do NOT
    # also call importlib.reload here — that would re-run module-level code a second time,
    # creating the engine twice and calling os.makedirs twice.)
    sys.modules.pop("daily_player_upload", None)
    module = importlib.import_module("daily_player_upload")

    yield module

    sys.modules.pop("daily_player_upload", None)
```

**Verify**: covered by Step 5's test run.

### Step 5: Write the characterization tests

Create `tests/test_daily_player_upload.py`. These tests lock in the **current,
correct** behavior (single-file load, name standardization, and dedup against rows
already in the DB). Do NOT add a multi-file-in-one-run test here — that is plan 003's
regression test for a bug this plan does not fix.

```python
import os

import pandas as pd

from tests.helpers import write_player_xlsx, make_rows


def _count(engine, table):
    return len(pd.read_sql_query(f"SELECT * FROM {table}", engine))


def test_single_file_loads_logs_and_learns_players(player_upload):
    mod = player_upload
    rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (2, "Beta Player", "2025-11-01", 20),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    processed, overwritten = mod.main()

    assert processed == 1
    assert _count(mod.engine, "player_logs") == 3      # all three game logs inserted
    assert _count(mod.engine, "dim_players") == 2      # two distinct players learned


def test_player_name_standardization_applied(player_upload):
    mod = player_upload
    # "GG Jackson" is mapped to "Gregory Jackson" in mappings.PLAYER_NAME_MAP
    rows = make_rows([(10, "GG Jackson", "2025-11-01", 18)])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    names = pd.read_sql_query("SELECT PLAYER FROM player_logs", mod.engine)["PLAYER"].tolist()
    assert names == ["Gregory Jackson"]


def test_rerun_with_same_logs_inserts_no_duplicates(player_upload):
    mod = player_upload
    rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    # First run
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()
    assert _count(mod.engine, "player_logs") == 2

    # Second run with an identical file (dedup is against rows already in the DB)
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()
    assert _count(mod.engine, "player_logs") == 2  # still 2 — no duplicates
```

**Verify**: `python3 -m pytest -q` → all 3 tests pass.

## Test plan

- New tests in `tests/test_daily_player_upload.py` cover: single-file load + player
  learning, name standardization via `PLAYER_NAME_MAP`, and dedup against existing DB
  rows across two separate runs.
- Structural pattern for future tests: the `player_upload` fixture + `write_player_xlsx`
  helper. Plans 003 and 004 reuse this harness.
- Verification: `python3 -m pytest -q` → 3 passing tests.

## Done criteria

ALL must hold:

- [ ] `python3 -m pip install -r requirements.txt -r requirements-dev.txt` exits 0.
- [ ] `python3 -m pytest -q` exits 0 with at least 3 passing tests.
- [ ] `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` exits 0.
- [ ] With `BIGDATABALL_DATA_DIR` unset, `daily_player_upload.BASE_DATA_PATH` still
      resolves to the `My Drive` path or `<repo>/Data` (fallback unbroken).
- [ ] `git status` shows only the in-scope files changed/created.
- [ ] `plans/README.md` status row for 002 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- `pip install` fails because the environment has no network access to PyPI.
- The reload-based fixture does not pick up the temp dir (e.g. `mod.DB_PATH` still
  points at `<repo>/Data`) — the module may have additional import-time caching not
  captured in "Current state"; report what you see.
- Any characterization test fails on the **current** code — that would mean the
  behavior these tests assume is already broken; report the failure rather than
  editing the script to make it pass (this plan must not change upload logic).
- `write_player_xlsx` produces a file the script rejects (e.g. a `KeyError` on
  `PLAYER_ID`/`DATE`); the raw-column assumptions in "Current state" may be wrong —
  report the actual error.

## Maintenance notes

- The `BIGDATABALL_DATA_DIR` override is also useful beyond tests (running the
  pipeline against an arbitrary data dir). Plan 005 generalizes this seam to the other
  scripts (`create_summary_tables.py`, the exporters, `run_db_patch.py`).
- A reviewer should confirm the env branch is **prepended** (highest precedence) and
  that the `G:` and `Data/` branches are byte-for-byte unchanged.
- Future: when plan 003 fixes the multi-file dedup bug, its regression test belongs in
  `tests/test_daily_player_upload.py` using this same fixture.
