# Plan 012: Add DB-level UNIQUE constraint to log tables

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3844392..HEAD -- daily_player_upload.py daily_fantasy_log_upload.py absence_ingestion.py check_ingest_duplicates.py`
> Compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition. `absence_ingestion.py` is in this list
> because Steps 3b–3c edit it heavily; confirm its `load_existing_absence_keys`,
> `_load_box_score_keys`, `absence_key`, and `to_sql` line references before implementing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (but MUST run `check_ingest_duplicates.py --remove` on the live DB before deploying — see Step 1)
- **Category**: data-integrity
- **Planned at**: commit `3844392`, 2026-06-21. **Refreshed at reconcile 2026-07-19
  (`967d88a`)**: the finding holds and has **grown** — plan 013 (merged `#38`) added a third
  log table, `player_absences`, with the exact same pattern (in-memory key-set dedup +
  `to_sql(if_exists="append")`, no DB-level constraint), so this plan now covers it too
  (Step 3b, added at reconcile). Line-number drift from plan 013's wiring, all verified:
  in `daily_player_upload.py`, `initialize_database()` now starts at line 34 and the
  `truly_new_logs_df.to_sql(...)` is at lines 228–230; `main()` now returns a **3-tuple**
  `(processed_count, overwritten_count, absences_count)` (line 278) — irrelevant to this
  plan's changes, but don't be surprised by it. In `daily_fantasy_log_upload.py`,
  `initialize_database()` is still at line 41 and the log `to_sql` is at line 250.
  The excerpted code below is otherwise unchanged. Full suite is now 47 tests (was 38).
- **Revised 2026-07-21 (review of this plan)**: this plan now specifies indexing
  `player_absences` on **`(PLAYER_ID, DATE)`** — the same key as the other two tables —
  instead of `(PLAYER_ID, GAME_ID)`. **This is target work, not yet applied**: the live
  `absence_ingestion.py` still builds `PLAYER_ID_GAMEID` keys and has no
  `ensure_unique_index`; Steps 3b–3c below are what make the change. Grounds (all
  code-verified, superseding the earlier
  "GAME_ID may be missing" reasoning, which was unfounded): (1) `check_ingest_duplicates.py`
  already declares `(PLAYER_ID, DATE)` the natural key for **all three** tables including
  `player_absences` (`:86-88`, docstring `:17-18`), so the current GAME_ID absence dedup is
  out of step with the very tool meant to clean that table, and this plan's own Step 1
  precondition validates absences on `(PLAYER_ID, DATE)` while old Step 3b indexed on
  GAME_ID — a self-contradiction; (2) plan 013's post-merge column rename to `DATE`/`PLAYER`
  was itself done so `check_ingest_duplicates` would work — DATE alignment is the intended
  direction; (3) `DATE` is uniformly `TEXT` across all three tables while `GAME_ID`/`PLAYER_ID`
  have a FLOAT-vs-INTEGER split in `fantasy_logs` (tracked separately in plan 014). Because a
  DATE index and the in-memory dedup key must match, the absence dedup **and** the box-score
  conflict filter are re-keyed to DATE by this plan in the same change (new Step 3c). This
  supersedes plan 013's design-decision-1 dedup-key choice.
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

**`daily_player_upload.py:33-47`** — `initialize_database()` creates `dim_players`
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
- `absence_ingestion.py` — add the unique index on `player_absences` (Step 3b) AND re-key
  the absence dedup + box-score conflict filter from GAME_ID to DATE (Step 3c)
- `tests/test_daily_player_upload.py` — add one regression test for the constraint
- `tests/test_daily_fantasy_log_upload.py` — add one regression test for the constraint
- `tests/test_absence_ingestion.py` — add one regression test for the `player_absences` index (Step 5b)

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

**Step 1a (CRITICAL — do before any `--remove`): preflight `player_absences` for
distinct-GAME_ID collisions.** `check_ingest_duplicates.py` groups `player_absences` on
`(PLAYER_ID, DATE)` and `--remove` keeps only `MIN(rowid)` per group — so if the live table
holds two absence rows sharing `(PLAYER_ID, DATE)` but with **different `GAME_ID`** (allowed
under plan 013's old GAME_ID dedup, but a data anomaly given one game per team per day),
`--remove` would silently **delete one of them**. Run this query first and STOP for manual
review if it returns any rows — do NOT run `--remove` on `player_absences` until a human has
decided which row is correct:
```sql
SELECT "PLAYER_ID", "DATE", COUNT(DISTINCT "GAME_ID") AS distinct_games, COUNT(*) AS rows
FROM player_absences
GROUP BY "PLAYER_ID", "DATE"
HAVING COUNT(DISTINCT "GAME_ID") > 1;
```
Expected on a healthy DB: zero rows. If non-empty, these are genuine box-score/feed anomalies
— resolve them by hand (keep the correct game), then proceed. (The post-`--remove`
index-creation STOP condition is too late on its own: the row would already be gone.)

**This step is only needed for the live database. In CI / tests, the DB is fresh.**

**Verify**: `python3 check_ingest_duplicates.py` → exit 0, and the Step 1a query returns
zero rows.

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
`truly_new_logs_df.to_sql(...)` line (currently at lines 228–230):

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
`main()` (currently at line 250).

Current `initialize_database()` is at lines 41-55 — same structure as player_upload;
apply the identical change.

**Verify**: `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.

### Step 3b: Add the unique index to `player_absences` — on `(PLAYER_ID, DATE)`

`absence_ingestion.py` (added by plan 013) appends to `player_absences` with the same
in-memory-dedup-only pattern. **Index it on `(PLAYER_ID, DATE)`** — the same key as the
other two tables, and the key `check_ingest_duplicates.py` already treats as the natural key
for this table (`:86-88`). (This differs from the reconcile-era draft of this step, which
used `(PLAYER_ID, GAME_ID)`; see the 2026-07-21 revision note in Status for why.) Step 3c
re-keys the in-memory absence dedup to DATE so the two agree — do Step 3c together with this.

`absence_ingestion` has no `initialize_database()` — it receives an `engine` per call and
its `to_sql` happens inside `ingest_absences()` only when new rows survive the dedup. To
match the two-call pattern the upload scripts use (index created both from
`initialize_database()` AND after `to_sql`), the helper must tolerate a not-yet-created
table and be called in **two** places (see below):

```python
def ensure_unique_index(engine):
    """Unique index on (PLAYER_ID, DATE) — DB-level backstop for the in-memory
    absence_key dedup. Safe to call before the table exists (guards `no such table`)
    so an already-populated player_absences gets indexed even on a run that inserts
    zero new rows; also called right after to_sql so a first-ever insert is covered."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{ABSENCES_TABLE_NAME}_player_date
                ON {ABSENCES_TABLE_NAME} ("PLAYER_ID", "DATE")
                """
                )
            )
    except Exception as e:
        if "no such table" in str(e):
            pass  # table not created yet; the post-to_sql call will create the index
        else:
            raise
```

Call it in two places inside `ingest_absences()`:
1. **Early**, near the top (before the dedup/`to_sql` work) — this indexes an existing,
   already-populated `player_absences` even when the current run produces zero new rows.
   The `no such table` guard makes this a no-op on a brand-new DB.
2. **Immediately after** the `player_absences` `to_sql(...)` call (`:188`) — covers the
   first-ever run that creates the table.

Both are idempotent (`CREATE UNIQUE INDEX IF NOT EXISTS`), so calling twice is harmless.

**Note**: unlike the two upload scripts, `absence_ingestion.py` does NOT already import
`text` — it currently imports only `pandas` and `mappings` (lines 9–10) and does all its
SQL through pandas. Add `from sqlalchemy import text` alongside its existing imports as
part of this step, or the helper above raises `NameError` at runtime. With the early call,
a run in which zero absence rows survive still creates/ensures the index on an existing
table; on a brand-new DB where the table doesn't exist yet, the guard no-ops and the
post-`to_sql` call creates it on the first real insert.

**Behavior-change note**: `ingest_absences` dedups incoming rows only against
`existing_keys` (`:149`), not against each other within one file. With this new UNIQUE
index, a *single feed* that contains two rows sharing `(PLAYER_ID, DATE)` would now fail the
insert with `IntegrityError` (caught by the caller's try/except → file not archived), rather
than silently double-inserting as it does today. One-game-per-day makes this near-impossible
in real data, and that loud failure is the intended backstop — but be aware it is a change
from the prior silent behavior.

**Verify**: `python3 -m py_compile absence_ingestion.py` → exit 0.

### Step 3c: Re-key the absence dedup and box-score conflict filter from GAME_ID to DATE

For the `(PLAYER_ID, DATE)` index in Step 3b to match the in-memory filter, re-key the
absence dedup from GAME_ID to DATE. `DATE` is already normalized to `%Y-%m-%d` at
`absence_ingestion.py:118` (`df["DATE"] = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")`)
before any key is built, so string keys are stable. Change three spots:

1. **`load_existing_absence_keys` (`:53-65`)** — select and key on DATE:
   ```python
   df = pd.read_sql(
       f'SELECT DISTINCT "PLAYER_ID", "DATE" FROM {ABSENCES_TABLE_NAME}',
       engine,
   )
   return set(df["PLAYER_ID"].astype(str) + "_" + df["DATE"].astype(str))
   ```
   Keep the `"no such table"` → empty-set guard.

2. **`ingest_absences` `absence_key` (`:139`)** — build from DATE:
   ```python
   df["absence_key"] = df["PLAYER_ID"].astype(str) + "_" + df["DATE"].astype(str)
   ```

3. **`_load_box_score_keys` (`:68-84`)** — select and key on DATE, and drop the now-unneeded
   `"no such column"` tolerance (DATE is always present in `player_logs`), but KEEP the
   `"no such table"` tolerance (a standalone `backfill_player_absences.py` run can call this
   before any box scores exist — it must return an empty set, not raise). Intended final
   form:
   ```python
   try:
       df = pd.read_sql('SELECT "PLAYER_ID", "DATE" FROM player_logs', engine)
       return set(df["PLAYER_ID"].astype(str) + "_" + df["DATE"].astype(str))
   except Exception as e:
       if "no such table" in str(e):
           return set()
       raise
   ```
   This is the one genuine behavior change: the box-score-wins conflict filter now matches
   absences to box scores on `(PLAYER_ID, DATE)` instead of `(PLAYER_ID, GAME_ID)`. Because
   NBA plays one game per team per day, both keys identify the same box-score row, so the
   outcome is unchanged for well-formed data. Also update the docstrings of these three
   functions (they currently say "PLAYER_ID_GAMEID") to say `PLAYER_ID_DATE`.

Leave the inserted `GAME_ID` **column** untouched — it is still selected into
`player_absences` (`:175-188`); only the key derivation changes.

**Verify**: `python3 -m py_compile absence_ingestion.py` → exit 0; and
`python3 -m pytest -q tests/test_absence_ingestion.py` → all pass (see Step 5b note — no
existing absence test changes behavior under this re-key).

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

    # The index must exist AND be unique (checking the name alone would pass
    # for a non-unique index).
    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("player_logs")
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    # Assert the indexed columns explicitly — `unique` alone doesn't prove the key is
    # (PLAYER_ID, DATE); a different unique index would also satisfy the checks above.
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]
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
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    # Assert the indexed columns explicitly — `unique` alone doesn't prove the key is
    # (PLAYER_ID, DATE); a different unique index would also satisfy the checks above.
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]
```

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py::test_unique_index_exists_on_fantasy_logs` → 1 passed.

### Step 5b: Add a regression test to `test_absence_ingestion.py` (added at reconcile 2026-07-19)

Add to `tests/test_absence_ingestion.py`, following the style of its existing tests
(they use the `player_upload` fixture and the multi-sheet helpers from `tests/helpers.py`
— model the setup on the first test in that file):

```python
def test_unique_index_exists_on_player_absences(player_upload):
    """ensure_unique_index must create a unique index on player_absences after
    the first absence insert."""
    from sqlalchemy import inspect
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )
    mod.main()

    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("player_absences")
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    # Assert the indexed columns explicitly — `unique` alone doesn't prove the key is
    # (PLAYER_ID, DATE); a different unique index would also satisfy the checks above.
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]
```

Add a second test that proves the *dedup behavior* is keyed on DATE (not GAME_ID) — two
absence rows with the same `(PLAYER_ID, DATE)` but different `GAME_ID` must collapse to one
row. Under the old GAME_ID key both would survive; under the new DATE key only one does:

```python
def test_absence_dedup_is_keyed_on_date_not_game_id(player_upload):
    """Two absence rows sharing (PLAYER_ID, DATE) but with different GAME_IDs must
    dedup to a single row — proving the in-memory key is DATE-based, not GAME_ID-based."""
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    # Same player (99) and DATE, two different GAME_IDs. No box score for player 99,
    # so the conflict filter does not remove either; only the DATE dedup applies.
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DND", "REST"),
        ("2025-11-01", 22500002, "Houston", "Dallas", 99, "Beta Bench", "DND", "REST"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )
    mod.main()  # must NOT raise IntegrityError — the in-memory DATE dedup drops the 2nd row

    absence_dates = pd.read_sql_query(
        "SELECT PLAYER_ID, DATE FROM player_absences WHERE PLAYER_ID = 99", mod.engine
    )
    assert len(absence_dates) == 1, f"Expected 1 row (DATE-keyed dedup); got {len(absence_dates)}"
```

Note this also confirms the in-memory filter and the UNIQUE index agree: if the dedup were
still GAME_ID-keyed, both rows would pass the filter and the second `to_sql` would raise
`IntegrityError` against the `(PLAYER_ID, DATE)` index — so a failure here signals Step 3c
was not applied (or was applied inconsistently with Step 3b).

**Before writing these tests, read the existing tests in `tests/test_absence_ingestion.py`**
— the `make_rows`, `make_absence_rows`, and `write_player_xlsx_with_absences` call shapes
above mirror `test_single_file_loads_absences_and_learns_players` (the first test in that
file) and `tests/helpers.py`; the helpers are authoritative. Note `make_absence_rows` takes
`(game_date, game_id, team, opponent, player_id, player_name, status, reason)` tuples. If
the helper signatures don't accommodate this test, STOP and report rather than modifying
`tests/helpers.py` (helpers are out of scope for this plan).

**Re-key regression check (Step 3c):** the existing absence tests were read during this
review and none change behavior under the GAME_ID→DATE re-key, because in every one each
player's DATE maps 1:1 to its GAME_ID:
- `test_conflict_rows_excluded_box_score_wins` — box score and conflicting absence share
  `(PLAYER_ID=50, DATE=2025-11-01)`, so the DATE-keyed conflict filter still drops row 50
  and keeps row 60. Passes unchanged.
- `test_dedup_across_files_in_one_run` / `test_rerun_with_same_file_...` — distinct DATEs
  give distinct keys exactly as distinct GAME_IDs did. Pass unchanged.
- `test_game_id_normalization_matches_player_logs` — joins `ON a.GAME_ID = p.GAME_ID` and
  asserts stored GAME_ID type; **unaffected** because GAME_ID remains a stored column.
If, contrary to this, any existing absence test fails after Step 3c, STOP and report — do
not weaken the test to make it pass.

**Verify**: `python3 -m pytest -q tests/test_absence_ingestion.py` → all pass (9 existing + 2 new).

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

Four new regression tests:
- `tests/test_daily_player_upload.py::test_unique_index_prevents_silent_duplicate`
  — re-ingesting the same file produces 1 row (not 2) AND the unique index on
  `["PLAYER_ID", "DATE"]` is present.
- `tests/test_daily_fantasy_log_upload.py::test_unique_index_exists_on_fantasy_logs`
  — after first ingest, the unique `["PLAYER_ID", "DATE"]` index exists on `fantasy_logs`.
- `tests/test_absence_ingestion.py::test_unique_index_exists_on_player_absences`
  — after the first absence insert, the unique `["PLAYER_ID", "DATE"]` index exists on
  `player_absences`.
- `tests/test_absence_ingestion.py::test_absence_dedup_is_keyed_on_date_not_game_id`
  — two same-`(PLAYER_ID, DATE)`, different-`GAME_ID` absence rows collapse to one,
  proving the dedup key is DATE (behavioral complement to the metadata assertions).

These tests verify the index existence and columns (via `sqlalchemy.inspect`) AND the
correctness of the DATE-keyed dedup behavior (row count). They use the existing fixtures — no
new fixtures needed.

## Done criteria

ALL must hold:

- [ ] `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py absence_ingestion.py` exits 0
- [ ] `python3 -m pytest -q` exits 0 with 4 new tests in scope
- [ ] On a test DB: `sqlalchemy.inspect(engine).get_indexes("player_logs")` returns an index with "player_date" in the name, `unique == True`, **and `column_names == ["PLAYER_ID", "DATE"]`**
- [ ] On a test DB: `sqlalchemy.inspect(engine).get_indexes("fantasy_logs")` returns an index with "player_date" in the name, `unique == True`, **and `column_names == ["PLAYER_ID", "DATE"]`**
- [ ] On a test DB (after an absence insert): `sqlalchemy.inspect(engine).get_indexes("player_absences")` returns an index with "player_date" in the name, `unique == True`, **and `column_names == ["PLAYER_ID", "DATE"]`**
- [ ] `absence_ingestion.py`'s dedup + conflict-filter keys are built from DATE, not GAME_ID (Step 3c); all 9 existing `test_absence_ingestion` tests still pass unchanged
- [ ] No change to `check_ingest_duplicates.py` or any export script (`git diff --name-only`)
- [ ] `plans/README.md` status row for 012 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows existing duplicates on the live DB that cannot be removed by
  `check_ingest_duplicates.py --remove` (e.g. the script itself errors). Do not
  proceed past Step 1 until the live DB is clean.
- `CREATE UNIQUE INDEX` on the live `player_logs`, `fantasy_logs`, or `player_absences`
  fails with `UNIQUE constraint failed` — this means `check_ingest_duplicates.py --remove`
  did not fully clean that table. Investigate and re-run it. For `player_absences`
  specifically, a failure here can mean the table currently holds two rows sharing
  `(PLAYER_ID, DATE)` but with different `GAME_ID` — the old GAME_ID dedup allowed that but
  the new DATE index (and `check_ingest_duplicates`, which already keys absences on DATE)
  will not. `--remove` keeps `MIN(rowid)` per `(PLAYER_ID, DATE)`; if the two rows differ in
  other columns, review before removing.
- The `try/except "no such table"` block in the updated `initialize_database()` swallows
  a different `OperationalError` that should propagate. Confirm the specific string
  `"no such table"` is in `str(e)` before suppressing.
- Any previously passing test starts failing after the code changes in Steps 2–3c. (Per the
  Step 5b re-key regression check, none should — investigate rather than editing the test.)

## Maintenance notes

- **First-run behavior**: On a brand-new installation (no DB yet), `initialize_database()`
  silently skips the index creation (table not yet created). The `ensure_unique_index()`
  call immediately after `to_sql()` in `main()` covers this: the index is created from the
  very first insert, not deferred to the second run.
- **`check_ingest_duplicates.py --remove`** removes duplicates with an in-place
  `DELETE ... WHERE rowid NOT IN (SELECT MIN(rowid) ...)` — it does NOT drop or recreate
  the table. The unique indexes are preserved automatically because the schema is untouched.
  No post-`--remove` index verification is required.
- A reviewer should confirm the try/except in `initialize_database()` catches ONLY the
  `"no such table"` error and re-raises everything else — silencing an unexpected
  OperationalError would hide real problems.
- Deferred: adding the unique index to tables created by `check_ingest_duplicates.py`'s
  internal `CREATE TABLE player_logs_dedup ...` is out of scope here. If the safety-net
  script is refactored, revisit whether the index should be part of its DDL.
