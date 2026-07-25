# Plan 022: Close the SQLite connection on every exit path in `run_db_patch.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ba82f6a..HEAD -- src/bigdataball/run_db_patch.py src/bigdataball/create_log_indexes.py tests/conftest.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ba82f6a`, 2026-07-24
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/53

## Why this matters

`src/bigdataball/run_db_patch.py` opens a raw `sqlite3` connection and closes it
only on the normal path. If the loop re-raises an unexpected
`sqlite3.OperationalError` (anything other than the "no such table"/"no such
column" cases it deliberately skips), or any other exception fires mid-loop, the
function exits **before** `conn.close()` — the connection is left to be reclaimed
by garbage collection rather than closed deterministically, and any UPDATEs
already issued sit in an open, uncommitted transaction that holds a write lock on
`nba_fantasy_logs.db` for as long as the object survives.

Real-world impact is low — this is a one-time manual migration script — but every
*other* raw-`sqlite3` script in the package already uses `try/finally`
(`create_log_indexes.py`, `seed_map_teams.py`, `check_ingest_duplicates.py`,
`patch_absence_column_names.py`), so this file is the odd one out. Making it match
is cheap, removes a lock-retention footgun on a script that writes to the live DB,
and closes a repo-wide consistency gap. It also gives the file its first test
coverage (`docs/codebase/TESTING.md` currently lists `run_db_patch.py` under "No
tests").

This finding was filed by the repo owner as issue #53 after the PR #52 review; it
is **pre-existing** behavior, not introduced by the src-layout migration.

## Current state

Files involved:

- `src/bigdataball/run_db_patch.py` — the one-time retroactive player-name fix.
  Single function `fix_player_names()`; connection opened at line 18, closed only
  at line 70.
- `src/bigdataball/create_log_indexes.py` — the exemplar for the correct pattern
  in this repo (lines 156–177).
- `tests/conftest.py` — holds the repo's env-seam fixtures (`player_upload`,
  `fantasy_upload`). This plan adds a **local** fixture in the new test file
  instead of extending conftest.

### `src/bigdataball/run_db_patch.py` as it exists today (verbatim, lines 12–75)

```python
def fix_player_names():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return

    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Define the tables and columns that may contain player names to be corrected.
    # NOTE: Table and column names are hard-coded here and not from user input,
    # so using them in f-strings for SQL is safe in this context.
    tables_to_patch = {
        "dim_players": "PLAYER_NAME",
        "fantasy_logs": "PLAYER",
        "player_logs": "PLAYER",
        "fantasy_averages": "PLAYER",
    }

    print("Starting retroactive player name correction across all relevant tables...")
    total_updates = 0

    for incorrect_name, correct_name in mappings.PLAYER_NAME_MAP.items():
        print(f"\n--- Applying mapping: '{incorrect_name}' -> '{correct_name}' ---")

        for table, column in tables_to_patch.items():
            try:
                # Check for records to update using parameter binding for safety
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                    (incorrect_name,),
                )
                count = cursor.fetchone()[0]

                if count > 0:
                    print(f"  > Found {count} record(s) in '{table}'. Updating...")
                    # Execute the update
                    cursor.execute(
                        f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                        (correct_name, incorrect_name),
                    )
                    total_updates += cursor.rowcount

            except sqlite3.OperationalError as e:
                # This handles cases where a table or column might not exist
                if "no such table" in str(e) or "no such column" in str(e):
                    print(f"  > Skipping '{table}': Table or column not found.")
                else:
                    # Re-raise other operational errors
                    raise e

    print("\n--- Patch Summary ---")
    if total_updates > 0:
        print(f"Committing {total_updates} total changes to the database.")
        conn.commit()
    else:
        print("No changes were needed.")

    conn.close()
    print("Database connection closed.")


if __name__ == "__main__":
    fix_player_names()
```

The module header (lines 1–10, do NOT change it):

```python
import sqlite3
import os
from . import mappings
from . import paths

# --- Configuration: Match logic from main scripts ---
BASE_DATA_PATH = paths.resolve_base_data_path()

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
```

Note `DB_PATH` is resolved at **import time**, which is why the test fixture below
must set `BIGDATABALL_DATA_DIR` and then fresh-import the module.

### The repo's exemplar for this pattern — `src/bigdataball/create_log_indexes.py:156-177`

```python
    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Database: {DB_PATH}")
        results = {t: create_index(conn, t) for t in tables}

        print("\n--- Summary ---")
        for table, outcome in results.items():
            print(f"  {table:<18} {outcome}")

        # ... elided ...
        print("\nDone. All requested tables have the UNIQUE (PLAYER_ID, DATE) index.")
        return 0
    finally:
        conn.close()
```

Match this shape: `connect()` outside the `try`, everything else inside, a bare
`finally: conn.close()`.

### Conventions that apply

- **Maintenance scripts use raw `sqlite3.connect` + cursor** (not SQLAlchemy) —
  `docs/codebase/CONVENTIONS.md:35`. Keep it that way; do **not** convert this
  file to SQLAlchemy.
- **Table/column names are hardcoded constants interpolated into f-strings; value
  parameters use bound `?` params** — `docs/codebase/CONVENTIONS.md:45`. Preserve
  both; do not "fix" the f-strings.
- **`sqlite3.OperationalError` is filtered on `"no such table"`/`"no such column"`
  to skip absent tables** — `docs/codebase/CONVENTIONS.md:52`. This skip path is
  intentional and must keep working exactly as it does now.
- Tests use the **env-seam pattern**: set `BIGDATABALL_DATA_DIR`, `sys.modules.pop`
  the target module, then `importlib.import_module` so module-level path code
  re-runs against the temp dir. See `tests/conftest.py` (`player_upload` fixture)
  and `docs/codebase/TESTING.md` "Strategy / Patterns".
- Test files are flat `pytest` functions with `monkeypatch`/`tmp_path` — no
  classes. See `tests/test_paths.py` for the smallest example.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install package (editable) | `pip install -e .` | exit 0 |
| Install dev deps | `pip install -r requirements-dev.txt` | exit 0 |
| Full suite (before change) | `python -m pytest -q` | `68 passed` |
| Full suite (after change) | `python -m pytest -q` | `72 passed` |
| New file only | `python -m pytest -q tests/test_run_db_patch.py` | `4 passed` |
| Confirm no stray close | `grep -n "conn.close()" src/bigdataball/run_db_patch.py` | exactly **one** match, inside a `finally:` block |

If a repo-local `.venv` exists, use `.venv/bin/python -m pytest -q` instead of
`python -m pytest -q`.

## Scope

**In scope** (the only files you should create/modify):
- `src/bigdataball/run_db_patch.py` (modify `fix_player_names()` only)
- `tests/test_run_db_patch.py` (create)
- `plans/README.md` (status row update only)

**Out of scope** (do NOT touch, even though they look related):
- `src/bigdataball/verify_db_patch.py` — read-only script (`SELECT COUNT(*)` only,
  never commits). Issue #53 explicitly scopes the required change to
  `run_db_patch.py` and calls this one lower priority. Leaving it out keeps the
  diff reviewable; it is recorded as deferred follow-up below.
- `src/bigdataball/create_log_indexes.py`, `seed_map_teams.py`,
  `check_ingest_duplicates.py`, `patch_absence_column_names.py` — these already
  use `try/finally`. Nothing to do.
- `src/bigdataball/mappings.py` — do not add, remove, or reorder entries in
  `PLAYER_NAME_MAP`. The tests below read the real map rather than assuming
  specific names.
- `tests/conftest.py` — do not add a fixture there; this plan's fixture is local
  to the new test file.
- The f-string SQL and the "no such table"/"no such column" skip branch — both are
  documented conventions, not defects.

## Git workflow

- Branch: `advisor/022-run-db-patch-connection-cleanup` (or the repo's
  branch-naming convention if one is evident from `git log --oneline`).
- Commit message style: match `git log` — imperative, no prefix, e.g.
  "Close the SQLite connection on every exit path in run_db_patch".
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish the baseline

Run the full suite before changing anything.

**Verify**: `python -m pytest -q` → `68 passed`

If the count differs, the repo has drifted since this plan was written — treat it
as a STOP condition and report the actual count.

### Step 1: Wrap the body of `fix_player_names()` in `try/finally`

In `src/bigdataball/run_db_patch.py`, restructure `fix_player_names()` so that:

1. `conn = sqlite3.connect(DB_PATH)` stays **outside** the `try` (matching
   `create_log_indexes.py:156`) — if `connect()` itself fails there is nothing to
   close.
2. Everything from `cursor = conn.cursor()` through the final
   `print("Database connection closed.")`-equivalent moves **inside** the `try`,
   indented one level.
3. Before the `raise` in the `else` branch of the `except sqlite3.OperationalError`
   handler, call `conn.rollback()` so a partially-applied batch is not left
   pending. Keep the re-raise.
4. A `finally:` block closes the connection and prints the closing message.

Target shape (the surrounding loop body is unchanged — only indentation, the new
`rollback()`, and the `finally` are new):

```python
    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        # ... tables_to_patch dict, prints, and the mapping loop unchanged,
        #     indented one extra level ...

            except sqlite3.OperationalError as e:
                # This handles cases where a table or column might not exist
                if "no such table" in str(e) or "no such column" in str(e):
                    print(f"  > Skipping '{table}': Table or column not found.")
                else:
                    # Roll back the partially-applied batch before re-raising so
                    # no half-finished patch is left pending on the connection.
                    conn.rollback()
                    # Re-raise other operational errors
                    raise e

        print("\n--- Patch Summary ---")
        if total_updates > 0:
            print(f"Committing {total_updates} total changes to the database.")
            conn.commit()
        else:
            print("No changes were needed.")
    finally:
        conn.close()
        print("Database connection closed.")
```

Preserve every existing comment, print string, and the `total_updates` accounting
verbatim. Do not rename anything. Do not change the early
`if not os.path.exists(DB_PATH): ... return` guard at lines 13–15 (it returns
before any connection exists).

**Verify**:
- `grep -c "conn.close()" src/bigdataball/run_db_patch.py` → `1`
- `grep -n -A1 "finally:" src/bigdataball/run_db_patch.py` → shows `conn.close()`
  on the line after `finally:`
- `python -m pytest -q` → `68 passed` (no test covers this file yet; this only
  confirms nothing else broke)

### Step 2: Create `tests/test_run_db_patch.py` with the fixture

Create the file with this fixture at the top. It mirrors the `player_upload`
fixture in `tests/conftest.py` (env var → `sys.modules.pop` → `import_module`), but
is local to this file because no other test needs it.

```python
import importlib
import sqlite3
import sys

import pytest

from bigdataball import mappings


@pytest.fixture
def patch_module(tmp_path, monkeypatch):
    """Imports run_db_patch fresh with DB_PATH pointed at a temp SQLite file.

    run_db_patch resolves DB_PATH at import time from
    paths.resolve_base_data_path(), so the env var must be set before the import.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

    db_path = data_dir / "nba_fantasy_logs.db"
    # Create the DB file so the module's os.path.exists(DB_PATH) guard passes.
    sqlite3.connect(str(db_path)).close()

    sys.modules.pop("bigdataball.run_db_patch", None)
    module = importlib.import_module("bigdataball.run_db_patch")
    assert module.DB_PATH == str(db_path)

    yield module, str(db_path)

    sys.modules.pop("bigdataball.run_db_patch", None)
```

Helper for picking a real mapping entry (add below the fixture) — the tests must
not hardcode player names, because `mappings.PLAYER_NAME_MAP` changes over time:

```python
def first_mapping():
    """One (incorrect, correct) pair from the live PLAYER_NAME_MAP."""
    return next(iter(mappings.PLAYER_NAME_MAP.items()))
```

**Verify**: `python -m pytest -q tests/test_run_db_patch.py` → `no tests ran`
(the file has no test functions yet) or a collection message with 0 tests, and
**exit code 5** (`pytest`'s "no tests collected"). No errors/tracebacks.

### Step 3: Add the four tests

Append these four tests to `tests/test_run_db_patch.py`.

**Test 1 — happy path renames and commits.**

```python
def test_renames_and_commits(patch_module):
    module, db_path = patch_module
    incorrect, correct = first_mapping()

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dim_players (PLAYER_NAME TEXT)")
    conn.execute("INSERT INTO dim_players VALUES (?)", (incorrect,))
    conn.commit()
    conn.close()

    module.fix_player_names()

    # Re-open: proves the change was committed, not just pending.
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT PLAYER_NAME FROM dim_players").fetchall()
    conn.close()
    assert rows == [(correct,)]
```

**Test 2 — missing tables are skipped, not fatal.** Only `dim_players` exists; the
other three tables in `tables_to_patch` raise "no such table" and must be skipped.

```python
def test_missing_tables_are_skipped(patch_module, capsys):
    module, db_path = patch_module
    incorrect, correct = first_mapping()

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dim_players (PLAYER_NAME TEXT)")
    conn.execute("INSERT INTO dim_players VALUES (?)", (incorrect,))
    conn.commit()
    conn.close()

    module.fix_player_names()  # must not raise

    out = capsys.readouterr().out
    assert "Table or column not found" in out
    assert "Database connection closed." in out
```

**Test 3 — an unexpected `OperationalError` still closes the connection.**
`fantasy_averages` is created as a **view**, so the `SELECT COUNT(*)` succeeds
(count > 0) but the `UPDATE` fails with
`OperationalError: cannot modify fantasy_averages because it is a view` — a message
containing neither "no such table" nor "no such column", so the script re-raises.
`fantasy_averages` is the **last** key in `tables_to_patch`, so it is reached after
the other three.

```python
def test_unexpected_error_closes_connection(patch_module, monkeypatch):
    module, db_path = patch_module
    incorrect, correct = first_mapping()

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE base (PLAYER TEXT)")
    conn.execute("INSERT INTO base VALUES (?)", (incorrect,))
    # A view is readable but not updatable -> OperationalError on UPDATE.
    conn.execute("CREATE VIEW fantasy_averages AS SELECT PLAYER FROM base")
    conn.commit()
    conn.close()

    opened = []
    real_connect = sqlite3.connect

    def spy_connect(*args, **kwargs):
        created = real_connect(*args, **kwargs)
        opened.append(created)
        return created

    monkeypatch.setattr(module.sqlite3, "connect", spy_connect)

    with pytest.raises(sqlite3.OperationalError, match="is a view"):
        module.fix_player_names()

    assert len(opened) == 1
    # A closed sqlite3 connection raises ProgrammingError on any further use.
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")
```

**Test 4 — the failed run leaves no partially-committed rows.** `dim_players` is a
real table (first key, updated successfully) and `fantasy_averages` is the failing
view (last key), so the run dies with one pending UPDATE.

```python
def test_failed_run_commits_nothing(patch_module):
    module, db_path = patch_module
    incorrect, correct = first_mapping()

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dim_players (PLAYER_NAME TEXT)")
    conn.execute("INSERT INTO dim_players VALUES (?)", (incorrect,))
    conn.execute("CREATE TABLE base (PLAYER TEXT)")
    conn.execute("INSERT INTO base VALUES (?)", (incorrect,))
    conn.execute("CREATE VIEW fantasy_averages AS SELECT PLAYER FROM base")
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.OperationalError, match="is a view"):
        module.fix_player_names()

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT PLAYER_NAME FROM dim_players").fetchall()
    conn.close()
    assert rows == [(incorrect,)], "the aborted run must not leave committed rows"
```

**Verify**: `python -m pytest -q tests/test_run_db_patch.py` → `4 passed`

### Step 4: Confirm the whole suite

**Verify**: `python -m pytest -q` → `72 passed` (68 baseline + 4 new)

### Step 5: Confirm nothing outside scope changed

**Verify**: `git status --porcelain` → exactly these entries and nothing else
(note the leading space in the ` M` status codes):

```text
 M src/bigdataball/run_db_patch.py
?? tests/test_run_db_patch.py
 M plans/README.md
```

The third line appears only if you are updating the index — skip it if a reviewer
told you they maintain it.

## Test plan

- **New file**: `tests/test_run_db_patch.py` — 4 tests, listed in Step 3:
  1. `test_renames_and_commits` — happy path (the behavior that must not regress).
  2. `test_missing_tables_are_skipped` — the documented "no such table" skip path
     still works and still prints the closing message.
  3. `test_unexpected_error_closes_connection` — **the regression test for this
     plan**: an unexpected `OperationalError` propagates *and* the connection is
     deterministically closed.
  4. `test_failed_run_commits_nothing` — an aborted run leaves no committed rows.
- **Structural pattern to follow**: `tests/test_paths.py` (flat functions,
  `monkeypatch`) for style; `tests/conftest.py`'s `player_upload` fixture for the
  fresh-import env-seam mechanics.
- Note on test 4: closing a `sqlite3` connection with a pending transaction
  implicitly rolls it back, so this test would also pass without the explicit
  `conn.rollback()` added in Step 1. It is asserting the observable guarantee (no
  partial commit), not the presence of the `rollback()` call; the explicit call
  makes the intent legible and the outcome independent of close-time semantics.
  Keep both.
- Verification: `python -m pytest -q` → `72 passed`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "conn.close()" src/bigdataball/run_db_patch.py` returns `1`
- [ ] `grep -c "finally:" src/bigdataball/run_db_patch.py` returns `1`
- [ ] `grep -c "conn.rollback()" src/bigdataball/run_db_patch.py` returns `1`
- [ ] `python -m pytest -q tests/test_run_db_patch.py` → `4 passed`
- [ ] `python -m pytest -q` → `72 passed`
- [ ] `test -f tests/test_run_db_patch.py; echo $?` returns `0` (the new file
      exists — `git diff` cannot show it, since it is untracked)
- [ ] `git status --porcelain` lists the two required entries from Step 5
      (` M src/bigdataball/run_db_patch.py`, `?? tests/test_run_db_patch.py`),
      plus ` M plans/README.md` only if you are updating the index, **and nothing
      else** — this, not `git diff --stat`, is the scope check, because `git diff`
      is blind to untracked files
- [ ] `git diff --stat` (tracked files only) shows
      `src/bigdataball/run_db_patch.py` and, optionally, `plans/README.md`
- [ ] `git diff src/bigdataball/run_db_patch.py` contains **no** change to any
      SQL string, print string, or the `tables_to_patch` dict — only indentation,
      the `try:`/`finally:` lines, the `conn.rollback()` line, and its comment
- [ ] `plans/README.md` status row updated (skip if a reviewer maintains the index)

## STOP conditions

Stop and report back (do not improvise) if:

- The baseline in Step 0 is not `68 passed`.
- `src/bigdataball/run_db_patch.py` does not match the "Current state" excerpt
  above (the file drifted since this plan was written).
- The view-based `OperationalError` trick in tests 3 and 4 does not produce a
  message containing `"is a view"` on your SQLite build — do **not** substitute a
  different failure mechanism (e.g. monkeypatching `cursor.execute`) without
  reporting first.
- Making the tests pass appears to require changing `mappings.PLAYER_NAME_MAP`,
  `tests/conftest.py`, or any file in the out-of-scope list.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- **For the reviewer**: the diff should be almost entirely re-indentation. Read it
  with `git diff -w src/bigdataball/run_db_patch.py` — that ignores whitespace and
  should leave only the `try:` / `finally:` / `conn.rollback()` lines plus the new
  comment. Anything else in that whitespace-ignoring diff is out of scope.
- **Deferred, deliberately**: `src/bigdataball/verify_db_patch.py` has the same
  shape (connect at line 17, `conn.close()` at line 45) but is read-only — it never
  commits and holds no write lock, so the failure mode this plan fixes doesn't
  apply. Issue #53 names it as lower priority. Fold the same `try/finally` in
  opportunistically if that file is ever touched for another reason.
- **Interacts with**: nothing in the daily pipeline — `run_db_patch.py` is invoked
  manually (`python -m bigdataball.run_db_patch`, see `CLAUDE.md`) and is not
  called by `daily_fantasy_log_upload.py` or any other module
  (`grep -rn "run_db_patch" src/` returns only the file itself).
- **Docs follow-up**: `docs/codebase/TESTING.md` lists `run_db_patch.py` under "No
  tests" (line 58) and its test-file inventory (lines 20–34) will be one file and
  4 tests out of date once this lands. Do **not** edit `docs/codebase/` in this
  plan — refresh it afterwards with the `codebase-doc-refresh` skill, which owns
  those files.
