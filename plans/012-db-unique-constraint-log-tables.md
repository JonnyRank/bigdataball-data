# Plan 012: Add DB-level UNIQUE constraint to log tables

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3844392..HEAD -- daily_player_upload.py daily_fantasy_log_upload.py check_ingest_duplicates.py`
> Compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (but MUST run `check_ingest_duplicates.py --remove` on the live DB before deploying — see Step 1)
- **Category**: data-integrity
- **Planned at**: commit `3844392`, 2026-06-21
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/30

## Why this matters

`player_logs` and `fantasy_logs` have no database-level uniqueness guarantee. De-
duplication is enforced entirely in-memory via an `existing_log_keys` set built at
the start of each upload script. If that logic regresses — a future edit, a new calling
pattern, a direct `to_sql` from a one-off script — duplicate `(PLAYER_ID, DATE)` rows
are silently inserted and inflate every player average. `check_ingest_duplicates.py`
exists precisely as an after-the-fact safety net (its docstring says so). Adding a
`UNIQUE` index to each table makes the DB the final authority: a duplicate insert fails
loudly at the DB layer rather than silently corrupting every computed average.

`docs/codebase/CONCERNS.md:4` documents this as the root architecture fragility.
Plan 003 (DONE) fixed the specific cross-file reset bug; this plan adds the missing
constraint so any future regression produces an `IntegrityError` rather than silent
data corruption.

## Current state

**`daily_player_upload.py:55-97`** — `initialize_database()` creates `dim_players`
with a PK, but does **not** create `player_logs` explicitly — it is created implicitly
by `to_sql(if_exists="append")` with no schema:

```python
# daily_player_upload.py:33-47
def initialize_database():
    with engine.connect() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {PLAYERS_TABLE_NAME} (
                "PLAYER_ID" INTEGER PRIMARY KEY,
                "PLAYER_NAME" TEXT
            );
        """))
        conn.commit()
```

```python
# daily_player_upload.py:222-225
truly_new_logs_df.to_sql(
    LOGS_TABLE_NAME, con=engine, if_exists="append", index=False
)
```

**`daily_fantasy_log_upload.py`** — same pattern: `initialize_database()` creates
`dim_players` only; `fantasy_logs` is created by `to_sql(if_exists="append")`.

**Neither `player_logs` nor `fantasy_logs` has a UNIQUE constraint or index.**
SQLite confirms this: `PRAGMA index_list(player_logs)` → empty.

**`check_ingest_duplicates.py:7-18`** — the docstring explicitly acknowledges the gap:
```
The root cause was that both upload scripts rebuild existing_log_keys from the DB
at startup (correct) but reset the in-memory set between files (bug — fixed in
plan 003). The DB layer has no enforcement; this script is the safety net.
```

**Proposed approach:** Add unique indexes *after* the tables exist. SQLite supports
`CREATE UNIQUE INDEX` on existing tables without DDL for the full schema. The unique
index is added in the `initialize_database()` functions so it is always present
(created idempotently on first run, ignored on subsequent runs if already there).

For the inserts: keep the existing in-memory `existing_log_keys` dedup as the primary
filter (prevents sending duplicates to the DB layer entirely). The unique index is a
last-resort safety net. When a duplicate does slip through the in-memory filter, the
current behavior is:
- Without constraint: duplicate is silently inserted ← the bug
- With constraint: `IntegrityError` is raised, caught by the existing `try/except`
  in the file-processing loop, appended to `pipeline_errors`, file is not archived

This means a duplicate-insert failure is now visible in the email report rather than
silent. **No change to pandas `to_sql` calls is needed** because the in-memory filter
should always prevent reaching the constraint; the constraint only fires if the filter
regresses.

## Commands you will need

| Purpose            | Command                                                                            | Expected on success         |
|--------------------|------------------------------------------------------------------------------------|-----------------------------|
| Check for dupes (live DB) | `python3 check_ingest_duplicates.py`                                      | exit 0 (no dupes) or fix with `--remove` |
| Syntax check       | `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py`        | exit 0                      |
| Verify index       | `python3 -c "import sqlite3, os, paths; db=os.path.join(paths.resolve_base_data_path(),'nba_fantasy_logs.db'); c=sqlite3.connect(db); print(c.execute('PRAGMA index_list(player_logs)').fetchall())"` | shows `idx_player_logs_player_date` |
| Run tests          | `python3 -m pytest -q`                                                             | all pass                    |

## Scope

**In scope** (the only files you should modify):
- `daily_player_upload.py` — extend `initialize_database()` to add the unique index
- `daily_fantasy_log_upload.py` — extend `initialize_database()` to add the unique index
- `tests/test_daily_player_upload.py` — add one regression test for the constraint
- `tests/test_daily_fantasy_log_upload.py` — add one regression test for the constraint

**Out of scope** (do NOT touch):
- `check_ingest_duplicates.py` — the safety-net tool is unchanged
- `create_summary_tables.py`, export scripts — no change
- The live database — the index creation is handled at runtime by `initialize_database()`

## Git workflow

- Branch: `advisor/012-db-unique-constraint` or current branch if instructed.
- One commit; message: `Add UNIQUE index on (PLAYER_ID, DATE) to log tables (plan 012)`.
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Verify the live DB is clean (pre-deployment check — do before any code change)

On the developer's machine, run:
```bash
python3 check_ingest_duplicates.py
```
- Exit 0 → DB is clean, safe to proceed.
- Non-zero → run `python3 check_ingest_duplicates.py --remove` to deduplicate first,
  then re-run the summary pipeline (`python3 create_summary_tables.py` etc.) to
  recompute averages from deduplicated data. Only then proceed.

**This step is only needed for the live database. In CI / tests, the DB is fresh.**

**Verify**: `python3 check_ingest_duplicates.py` → exit 0.

### Step 2: Add `ensure_unique_index()` and update `daily_player_upload.py`

The key insight from code review: the naive approach (index in `initialize_database()`
only) leaves the **first run unprotected** — `initialize_database()` runs before
`to_sql` creates the table, so the index creation is silently skipped. If any duplicate
is inserted during that first run, the second run's index creation will then fail.

The fix is an `ensure_unique_index()` helper that is called BOTH from
`initialize_database()` (covers subsequent runs) AND immediately after each `to_sql`
call in `main()` (covers the first-run table creation).

Current `initialize_database()` (lines 33-47):
```python
def initialize_database():
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
            CREATE TABLE IF NOT EXISTS {PLAYERS_TABLE_NAME} (
                "PLAYER_ID" INTEGER PRIMARY KEY,
                "PLAYER_NAME" TEXT
            );
            """
            )
        )
        conn.commit()
```

Replace with (add `ensure_unique_index` above, call it from `initialize_database`
AND after `to_sql` in `main()`):

```python
def ensure_unique_index():
    """Create the unique index on (PLAYER_ID, DATE) if the table exists.
    Called from initialize_database() (existing tables) and after to_sql()
    (first-run table creation), so the index is present from the very first insert.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{LOGS_TABLE_NAME}_player_date
                ON {LOGS_TABLE_NAME} ("PLAYER_ID", "DATE")
                """
                )
            )
    except Exception as e:
        if "no such table" in str(e):
            pass  # table not yet created; to_sql will create it, then we call this again
        else:
            raise


def initialize_database():
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
            CREATE TABLE IF NOT EXISTS {PLAYERS_TABLE_NAME} (
                "PLAYER_ID" INTEGER PRIMARY KEY,
                "PLAYER_NAME" TEXT
            );
            """
            )
        )
        conn.commit()
    ensure_unique_index()
```

In `main()`, add one call to `ensure_unique_index()` immediately after the
`truly_new_logs_df.to_sql(...)` line (currently at line ~223):

```python
                truly_new_logs_df.to_sql(
                    LOGS_TABLE_NAME, con=engine, if_exists="append", index=False
                )
                ensure_unique_index()  # idempotent; creates index on first run
```

This ensures the index exists from the moment the table is first populated, not on the
second run.

**Verify**: `python3 -m py_compile daily_player_upload.py` → exit 0.

### Step 3: Apply the same pattern to `daily_fantasy_log_upload.py`

Add the same `ensure_unique_index()` function (using `LOGS_TABLE_NAME = "fantasy_logs"`).
Call it from `initialize_database()` and after the `truly_new_logs_df.to_sql(...)` in
`main()` (currently at line ~249).

Current `initialize_database()` is at lines 41-55 — same structure as player_upload;
apply the identical change.

**Verify**: `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.

### Step 4: Add a regression test to `test_daily_player_upload.py`

Add to `tests/test_daily_player_upload.py`:

```python
def test_unique_index_prevents_silent_duplicate(player_upload):
    """After the first ingestion run, a second run with the same file must not insert
    duplicate rows — verified by checking the DB row count stays at 1, and the unique
    index created by ensure_unique_index must exist on player_logs."""
    from sqlalchemy import inspect
    mod = player_upload
    rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()

    # Write the same data again and re-run.
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()

    # Only one row — the in-memory dedup prevents the duplicate.
    assert count_rows(mod.engine, "player_logs") == 1

    # The unique index must exist.
    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("player_logs")
    index_names = [idx["name"] for idx in indexes]
    assert any("player_date" in name for name in index_names), (
        f"Unique index not found. Indexes: {index_names}"
    )
```

**Verify**: `python3 -m pytest -q tests/test_daily_player_upload.py::test_unique_index_prevents_silent_duplicate` → 1 passed.

### Step 5: Add a regression test to `test_daily_fantasy_log_upload.py`

Add to `tests/test_daily_fantasy_log_upload.py`:

```python
def test_unique_index_exists_on_fantasy_logs(fantasy_upload):
    """ensure_unique_index must create a unique index on fantasy_logs after first ingest."""
    from sqlalchemy import inspect
    mod = fantasy_upload
    rows = make_fantasy_rows([(1, "Alpha Player", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()

    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("fantasy_logs")
    index_names = [idx["name"] for idx in indexes]
    assert any("player_date" in name for name in index_names), (
        f"Unique index not found. Indexes: {index_names}"
    )
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_unique_index_exists_on_fantasy_logs` → 1 passed.

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

Two new regression tests:
- `tests/test_daily_player_upload.py::test_unique_index_prevents_silent_duplicate`
  — re-ingesting the same file produces 1 row (not 2) AND the unique index is present.
- `tests/test_daily_fantasy_log_upload.py::test_unique_index_exists_on_fantasy_logs`
  — after first ingest, the unique index exists on `fantasy_logs`.

These tests verify both the index existence (via `sqlalchemy.inspect`) and the correctness
of the dedup behavior (row count). They use the existing fixtures — no new fixtures needed.

## Done criteria

ALL must hold:

- [ ] `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` exits 0
- [ ] `python3 -m pytest -q` exits 0 with 2 new tests in scope
- [ ] On a test DB: `sqlalchemy.inspect(engine).get_indexes("player_logs")` returns at least one index with "player_date" in the name
- [ ] On a test DB: `sqlalchemy.inspect(engine).get_indexes("fantasy_logs")` returns at least one index with "player_date" in the name
- [ ] No change to `check_ingest_duplicates.py` or any export script (`git diff --name-only`)
- [ ] `plans/README.md` status row for 012 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows existing duplicates on the live DB that cannot be removed by
  `check_ingest_duplicates.py --remove` (e.g. the script itself errors). Do not
  proceed past Step 1 until the live DB is clean.
- `CREATE UNIQUE INDEX` on the live `player_logs` fails with `UNIQUE constraint failed`
  — this means `check_ingest_duplicates.py --remove` did not fully clean the table.
  Investigate and re-run it.
- The `try/except "no such table"` block in the updated `initialize_database()` swallows
  a different `OperationalError` that should propagate. Confirm the specific string
  `"no such table"` is in `str(e)` before suppressing.
- Any previously passing test starts failing after the code changes in Steps 2–3.

## Maintenance notes

- **First-run behavior**: On a brand-new installation (no DB yet), `initialize_database()`
  silently skips the index creation (table not yet created). The `ensure_unique_index()`
  call immediately after `to_sql()` in `main()` covers this: the index is created from the
  very first insert, not deferred to the second run.
- **`check_ingest_duplicates.py --remove`** recreates the tables as temp tables and renames.
  Verify after running it that the unique indexes survive (they should, since they're
  added to the renamed table — but if the tool's internal CREATE TABLE lacks them, they'd
  be lost). Run `sqlalchemy.inspect(engine).get_indexes("player_logs")` after any `--remove` run.
- A reviewer should confirm the try/except in `initialize_database()` catches ONLY the
  `"no such table"` error and re-raises everything else — silencing an unexpected
  OperationalError would hide real problems.
- Deferred: adding the unique index to tables created by `check_ingest_duplicates.py`'s
  internal `CREATE TABLE player_logs_dedup ...` is out of scope here. If the safety-net
  script is refactored, revisit whether the index should be part of its DDL.
