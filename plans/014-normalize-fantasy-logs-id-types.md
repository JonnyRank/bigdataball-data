# Plan 014: Normalize `fantasy_logs.PLAYER_ID` / `GAME_ID` to INTEGER

> **Executor instructions**: Follow this plan step by step. Run every verification command
> and confirm the expected result before moving to the next step. If anything in the "STOP
> conditions" section occurs, stop and report — do not improvise. When done, update the
> status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f142763..HEAD -- daily_fantasy_log_upload.py tests/helpers.py`
> Compare the "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (a mis-sequenced migration can re-insert every historical fantasy log — see
  the dedup-stability trap in Step 3)
- **Depends on**: none. **Plan 012 has now landed (DONE, merged `#43`)** — it indexes
  `fantasy_logs` on `(PLAYER_ID, DATE)` where DATE (TEXT) is the discriminator, so a float
  `PLAYER_ID` does not affect that index, and 012 did not need 014. The one live interaction:
  012's `if_exists="replace"` rebuild concern in Step 3 is no longer hypothetical — the unique
  index **exists** and Step 3 must re-create it (details updated in Step 3).
- **Category**: data-integrity / type-hygiene
- **Planned at**: commit `dacd007`, 2026-07-21 (from the plan 012 review).
- **Refresh (2026-07-22, reconcile @ `f142763`)**: plan 012 (merged `#43`) shifted every
  `daily_fantasy_log_upload.py` line anchor this plan cites and added a live unique index the
  Step 3 rebuild will drop. The excerpted **code is unchanged in content** — treat the excerpts
  as authoritative and the inline line numbers as approximate. Corrected anchors:
  sqlalchemy import **line 9** (unchanged); `iloc[1:]` dummy-row drop **line 179** (was 147);
  incoming dedup-key build **line 242** (was 207/209–211); DB-snapshot key build **lines
  133–142** (was 107–111); `truly_new_logs_df.to_sql` **line 282** (was 250–252);
  `fantasy_logs_count`/`fantasy_logs_overwritten` counters **lines 170–171** (was 138–139);
  success-email "Fantasy Logs Processed" line **385** (was 349–354); unmatched-DK warning /
  `(With Warnings)` block **lines 389–411** (was 376–380). `create_summary_tables.py` is
  unchanged, so its cited refs (`:257-259`, `:263`) still hold. **New interaction:** plan 012
  added an `ensure_unique_index()` helper (`daily_fantasy_log_upload.py:41-62`) and a
  standalone `create_log_indexes.py`; Step 3's `if_exists="replace"` rebuild DROPS the
  `idx_fantasy_logs_player_date` UNIQUE index, so the migration script MUST re-create it (now
  spelled out in Step 3).
- **Issue**: —

## Why this matters

In `fantasy_logs`, `PLAYER_ID` and `GAME_ID` are stored as **FLOAT/REAL**, whereas
`player_logs` and `player_absences` store the same fields as **INTEGER/BIGINT**. Root cause:
`daily_fantasy_log_upload.py` creates the table with a bare `to_sql` (no `dtype=`, no cast),
and pandas infers `float64` for any numeric column that contains a blank/`NaN` cell (int64
can't hold `NaN`), so the column lands with REAL affinity. (The `player_logs` box-score
sheet has no blanks in those columns → stays int64 → BIGINT; `absence_ingestion` explicitly
`.astype(int)`.)

Today this is **latent, not actively corrupting**:
- The fantasy dedup key is internally consistent (`"12345.0"` on both the DB-snapshot and
  incoming sides), so no duplicates slip through.
- `create_summary_tables.py` casts `PLAYER_ID` back to int (`:257-259`) and forces
  `Integer()` SQL type (`:263`) before writing `fantasy_averages`, so the float never
  propagates downstream.

The hazard is future foot-guns: any SQL join or pandas merge that crosses `fantasy_logs`
with another table on `PLAYER_ID`/`GAME_ID` works only by numeric coercion, and any *string*
key crossing tables breaks silently (`"12345.0" != "12345"`). This plan removes the
inconsistency at the source.

## Current state

**`daily_fantasy_log_upload.py:282-284`** — the log insert, no cast, no `dtype` (plan 012
added an `ensure_unique_index()` call immediately after it — see Step 3):

```python
truly_new_logs_df.to_sql(
    LOGS_TABLE_NAME, con=engine, if_exists="append", index=False
)
```

The incoming dedup key is built above (`:242`) as
`cleaned_data["PLAYER_ID"].astype(str) + "_" + cleaned_data["DATE"]`, and the DB snapshot key
at `:133-142`. With a float `PLAYER_ID` both sides produce `"12345.0"` — consistent today.

Imports (`:9`): `from sqlalchemy import create_engine, text` — `Integer`/`BigInteger` is NOT
imported yet.

**Test-fixture note (verified):** `tests/helpers.py:write_fantasy_xlsx` writes a dummy
all-`None` row (consumed by the script's `iloc[1:]`) and defines only
`cols = ["PLAYER_ID", "PLAYER", "DATE"]` — **no `GAME_ID`**. The `None` upcasts `PLAYER_ID`
to `float64` before `iloc` drops the row, so the fixture already reproduces the FLOAT bug for
`PLAYER_ID`. `GAME_ID` is absent from the fixture, so any cast on it must be guarded by an
`if "GAME_ID" in ...` presence check, or the existing fantasy tests break.

## The two traps this plan must handle

1. **Dedup-key stability (the dangerous one).** The incoming-cast and the existing-data
   migration MUST ship together. If only one lands, the key flips on one side only
   (`"12345.0"` vs `"12345"`), stops matching the DB snapshot, and **re-inserts every
   historical fantasy log as a "new" row** on the next daily run. Steps 2 and 3 are a single
   unit; do not deploy one without the other.
2. **Affinity requires a rebuild.** A plain `UPDATE ... SET PLAYER_ID = CAST(PLAYER_ID AS
   INTEGER)` does NOT stick — SQLite re-coerces the value back to REAL on store because the
   column's affinity is REAL. Changing affinity requires recreating the table with an
   explicit type. The Step 3 migration does this via `to_sql(if_exists="replace",
   dtype=...)`, which drops and recreates the table with INTEGER columns.

## Steps

### Step 1: Confirm the live storage types (pre-change diagnostic)

On the developer's machine (schema-safe — only queries `GAME_ID` if the column exists,
since the plan allows it to be absent):
```bash
python3 -c "
import sqlite3, os, paths
db = os.path.join(paths.resolve_base_data_path(), 'nba_fantasy_logs.db')
c = sqlite3.connect(db)
cols = [r[1] for r in c.execute('PRAGMA table_info(fantasy_logs)')]
id_cols = [x for x in ('PLAYER_ID', 'GAME_ID') if x in cols]
print('id columns present:', id_cols)
sel = ', '.join('typeof(\"%s\")' % x for x in id_cols)
print(c.execute('SELECT %s FROM fantasy_logs LIMIT 1' % sel).fetchone())
"
```
Expected: `typeof(...)` reports `real`/`float` for one or both ID columns. Record what you
see, and note whether `GAME_ID` is present at all. If both are already `integer`, the live DB
needs no migration (Step 3's data pass is a no-op) — but still apply Steps 2/4 so new inserts
stay INTEGER.

### Step 2: Cast incoming IDs in `daily_fantasy_log_upload.py`

Add `Integer` to the SQLAlchemy import (`:9`):
```python
from sqlalchemy import create_engine, text, Integer
```

In `main()`, after the player-name standardization block and **before** the dedup key is
built (`:242`), drop rows missing an ID and cast the present ID column(s) to int. The one
ordering that matters: this must land **after** the `iloc[1:]` dummy-row drop (`:179`) — by
that point the fixture's placeholder `None` row is already gone, and `dropna(subset=id_cols)`
removes any remaining null-ID rows, so `.astype(int)` cannot hit a `NaN`:
```python
# Normalize ID columns to integers so fantasy_logs matches player_logs /
# player_absences (which store PLAYER_ID / GAME_ID as INTEGER). Rows missing
# an ID are not valid player-game logs -> drop them before casting, but NEVER
# silently: a missing ID "can" happen and must be visible when it does.
id_cols = [c for c in ("PLAYER_ID", "GAME_ID") if c in cleaned_data.columns]
missing_mask = cleaned_data[id_cols].isna().any(axis=1)
dropped = int(missing_mask.sum())
if dropped:
    print(
        f"  > WARNING: dropping {dropped} fantasy row(s) in {file_name} with a "
        f"missing {id_cols} value (not a valid player-game log)."
    )
    fantasy_rows_dropped += dropped  # run-level counter, surfaced in the email (below)
    cleaned_data = cleaned_data.loc[~missing_mask]
for c in id_cols:
    # Reject fractional IDs rather than silently truncating them: astype(int)
    # would turn a corrupt 12345.7 into 12345 (a different, valid-looking player).
    frac = cleaned_data[c][cleaned_data[c] % 1 != 0]
    if not frac.empty:
        raise ValueError(
            f"{c} has non-integer values (refusing to truncate): {frac.unique().tolist()}"
        )
    cleaned_data[c] = cleaned_data[c].astype(int)
```

Pass an explicit `dtype` on the log insert (`:282-284`) so the table is created with INTEGER
affinity on a first run and stays correct:
```python
truly_new_logs_df.to_sql(
    LOGS_TABLE_NAME,
    con=engine,
    if_exists="append",
    index=False,
    dtype={c: Integer() for c in ("PLAYER_ID", "GAME_ID") if c in truly_new_logs_df.columns},
)
```
(`dtype` only takes effect when `to_sql` creates the table; on append to an existing table it
is ignored — that is why Step 3 must rebuild the existing table.)

**Surface the drop (required — must not be silent).** The daily pipeline runs headless, so a
`print()` alone isn't enough visibility; thread the drop count into the email report the way
`absence_rows_count` already is:
- Initialize `fantasy_rows_dropped = 0` once **before** the per-file loop (alongside
  `fantasy_logs_count = 0` / `fantasy_logs_overwritten = 0` at `daily_fantasy_log_upload.py:170-171`).
  The `fantasy_rows_dropped += dropped` line in the cast block accumulates across files.
- In the success-email body (the "Fantasy Logs Processed" line is at `:385`), add a line
  mirroring the existing count lines, e.g. `f"Fantasy Rows Dropped (missing PLAYER_ID/GAME_ID): {fantasy_rows_dropped}\n"`.
  If `fantasy_rows_dropped > 0`, also append a `--- WARNING ---`-style note (mirror the
  unmatched-DK-players warning block at `:389-411`) so a non-zero drop is unmissable, and set
  the `(With Warnings)` subject suffix that block already uses.
- A drop is a data-quality signal, **not** a hard failure — do NOT append it to
  `pipeline_errors` (that would mark the whole run "COMPLETED WITH ERRORS"); the count line +
  warning note is the right severity.

**Verify**: `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.

### Step 3: One-time migration of the existing `fantasy_logs` table

Create `patch_fantasy_id_types.py` (mirroring the existing `patch_absence_column_names.py`
precedent from plan 013 — read it for the path-resolution / engine idiom). It must:

1. Load the whole `fantasy_logs` table into pandas.
2. Drop rows with a null `PLAYER_ID` (or `GAME_ID` if present), then cast the present ID
   column(s) to int.
3. Write it back with `if_exists="replace"` + `dtype={...Integer()...}` so the recreated table
   has INTEGER affinity, **and re-create plan 012's UNIQUE index in the same transaction** (see
   the atomicity note below).

**Back up the DB first** (the same `.bak-*` habit `check_ingest_duplicates.py` uses), since
`if_exists="replace"` drops the table. The backup is the ultimate safety net.

**Make the rebuild + index recreation atomic (required — plan 012 is DONE).** Plan 012
(merged `#43`) created `idx_fantasy_logs_player_date`, a UNIQUE index on
`fantasy_logs("PLAYER_ID", "DATE")`. `to_sql(if_exists="replace")` DROPS the table and its
index, so the migration MUST re-create it — and it must do so in the **same transaction** as
the rebuild. Otherwise a `to_sql` that commits on its own engine connection followed by a
*separate* index-creation transaction can fail in between, leaving the table replaced but the
UNIQUE dedup backstop silently absent. SQLite has transactional DDL, so passing the open
`Connection` to `to_sql` enrolls its DROP/CREATE in one `engine.begin()` block that rolls back
both operations together on any failure. Sketch:
```python
import pandas as pd
from sqlalchemy import create_engine, Integer, text
import os, paths

DB_PATH = os.path.join(paths.resolve_base_data_path(), "nba_fantasy_logs.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

df = pd.read_sql_table("fantasy_logs", engine)
id_cols = [c for c in ("PLAYER_ID", "GAME_ID") if c in df.columns]
before = len(df)
df = df.dropna(subset=id_cols)
dropped = before - len(df)
if dropped:
    # Never drop silently — report it so a data anomaly is visible in the run log.
    print(f"WARNING: dropped {dropped} fantasy_logs row(s) with a missing {id_cols} value.")
for c in id_cols:
    frac = df[c][df[c] % 1 != 0]
    if not frac.empty:
        raise ValueError(
            f"{c} has non-integer values (refusing to truncate): {frac.unique().tolist()}"
        )
    df[c] = df[c].astype(int)

# Rebuild the table AND re-create plan 012's UNIQUE index in ONE transaction: passing the
# open `conn` to to_sql means its DROP/CREATE TABLE runs inside this begin() block, so a
# failure at either step rolls back both and the table is never left replaced-without-index.
with engine.begin() as conn:
    df.to_sql(
        "fantasy_logs", conn, if_exists="replace", index=False,
        dtype={c: Integer() for c in id_cols},
    )
    conn.execute(text(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_fantasy_logs_player_date '
        'ON fantasy_logs ("PLAYER_ID", "DATE")'
    ))
print(
    f"Rewrote fantasy_logs: {len(df)} rows ({dropped} dropped), {id_cols} cast to INTEGER; "
    "re-created UNIQUE idx_fantasy_logs_player_date in the same transaction."
)
```
(`create_log_indexes.py` builds the same index and refuses if duplicates exist — running it once
after the patch is a valid alternative to the inline `CREATE INDEX`, but it opens its own
connection, so it is **not** atomic with the rebuild; prefer the single-transaction form above.)
Verify with the Step-3 check below **plus**
`SELECT name FROM sqlite_master WHERE type='index' AND name='idx_fantasy_logs_player_date'`
returning one row.

**Deploy Steps 2 and 3 together** (see trap 1).

**Verify** (after running the patch on a copy of the live DB — same schema-safe form as Step 1):
```bash
python3 -c "
import sqlite3, os, paths
db = os.path.join(paths.resolve_base_data_path(), 'nba_fantasy_logs.db')
c = sqlite3.connect(db)
cols = [r[1] for r in c.execute('PRAGMA table_info(fantasy_logs)')]
id_cols = [x for x in ('PLAYER_ID', 'GAME_ID') if x in cols]
sel = ', '.join('typeof(\"%s\")' % x for x in id_cols)
print(id_cols, c.execute('SELECT %s FROM fantasy_logs LIMIT 1' % sel).fetchone())
"
```
Expected: every reported type is `integer` (e.g. `['PLAYER_ID', 'GAME_ID'] ('integer',
'integer')`, or `['PLAYER_ID'] ('integer',)` if the table has no GAME_ID).

### Step 4: Dedup-stability gate

After Steps 2+3 on a copy of the live DB, run one pipeline pass and confirm nothing is
re-inserted:
```bash
python3 check_ingest_duplicates.py            # expect exit 0 (no dupes)
```
Then, if feasible, re-run the fantasy ingestion against an already-archived file and confirm
`fantasy_logs` row count is unchanged (the int-keyed dedup still matches the migrated int
data). If the row count grows, **STOP** — the cast and migration are out of sync.

### Step 5: Regression test

Add to `tests/test_daily_fantasy_log_upload.py` (the `fantasy_upload` fixture drives the full
`main()`; follow `test_dedup_across_files_in_one_run` as the pattern):
```python
def test_player_id_stored_as_integer(fantasy_upload):
    """fantasy_logs.PLAYER_ID must be stored as INTEGER, matching player_logs /
    player_absences — not REAL (the pre-014 float-affinity bug)."""
    import pandas as pd
    mod = fantasy_upload
    rows = make_fantasy_rows([(1, "Alpha Player", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()

    types = pd.read_sql_query(
        "SELECT typeof(PLAYER_ID) AS t FROM fantasy_logs", mod.engine
    )["t"].unique().tolist()
    assert types == ["integer"], f"PLAYER_ID stored as {types}, expected ['integer']"

    # If GAME_ID is present (real feed has it; the current test fixture does not),
    # it must also be INTEGER. Conditional so the assertion no-ops when absent —
    # this makes GAME_ID a required gate the moment any fixture/data provides it,
    # without editing the shared helper.
    cols = pd.read_sql_query("SELECT * FROM fantasy_logs LIMIT 0", mod.engine).columns
    if "GAME_ID" in cols:
        gtypes = pd.read_sql_query(
            "SELECT typeof(GAME_ID) AS t FROM fantasy_logs", mod.engine
        )["t"].unique().tolist()
        assert gtypes == ["integer"], f"GAME_ID stored as {gtypes}, expected ['integer']"


def test_rerun_same_file_no_duplicates_after_int_cast(fantasy_upload):
    """The int cast must not break dedup: re-ingesting the same file inserts no
    duplicate rows."""
    mod = fantasy_upload
    rows = make_fantasy_rows([(1, "Alpha Player", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()
    assert count_rows(mod.engine, "fantasy_logs") == 1
```
Add `make_fantasy_rows` / `count_rows` to the file's imports if not already present.

**On testing the missing-ID drop:** a unit test that feeds a data row with a null
`PLAYER_ID`/`GAME_ID` and asserts the WARNING/count would need `write_fantasy_xlsx` to emit
such a row, which the current helper can't express — and `tests/helpers.py` is out of scope
(see the GAME_ID note below). The drop is instead surfaced at runtime (per-file `print`
WARNING + the `Fantasy Rows Dropped` email line). If you want unit coverage, STOP and raise
extending the helper rather than editing it unilaterally.

**Note on GAME_ID:** the current `write_fantasy_xlsx` helper has no GAME_ID column, so a
*dedicated* GAME_ID fixture is not added here (that would require editing the shared
`tests/helpers.py`, which risks other tests — out of scope). Instead the conditional
assertion above makes GAME_ID a required INTEGER gate automatically the moment any
fixture or real data provides the column, and Step 3's live-DB verification checks it on
the actual migrated table. If you conclude a dedicated GAME_ID fixture is warranted, STOP
and raise it rather than editing the shared helper unilaterally.

**Verify**: `python3 -m pytest -q tests/test_daily_fantasy_log_upload.py` → all pass.

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Scope

**In scope**:
- `daily_fantasy_log_upload.py` — import `Integer`, drop-null + cast ID cols, add `dtype` to `to_sql`.
- `patch_fantasy_id_types.py` — NEW one-time migration script.
- `tests/test_daily_fantasy_log_upload.py` — two regression tests.

**Out of scope** (do NOT touch):
- `tests/helpers.py` — shared fixture helpers.
- `daily_player_upload.py`, `absence_ingestion.py` — already store INTEGER.
- `create_summary_tables.py` — already casts output PLAYER_ID to int; no change needed.
- `create_log_indexes.py` and plan 012's other files — do not edit them. (Step 3 does
  re-create 012's `idx_fantasy_logs_player_date` from *inside* the new
  `patch_fantasy_id_types.py`, because the table rebuild drops it — that is in scope.)

## Done criteria

ALL must hold:
- [ ] `python3 -m py_compile daily_fantasy_log_upload.py patch_fantasy_id_types.py` exits 0
- [ ] `python3 -m pytest -q` exits 0 with the 2 new tests in scope
- [ ] `SELECT typeof(PLAYER_ID) FROM fantasy_logs` returns only `integer` on a test DB
- [ ] Re-ingesting an already-processed file leaves `fantasy_logs` row count unchanged
- [ ] `plans/README.md` status row for 014 updated

## STOP conditions

- After Steps 2+3, `fantasy_logs` row count grows on a re-run of an already-archived file
  (the cast and migration are out of sync — trap 1).
- The migration would drop a large fraction of rows at the `dropna(subset=id_cols)` step
  (i.e. many real rows have a null `PLAYER_ID`/`GAME_ID`) — that contradicts the assumption
  that such rows are invalid; report the count before proceeding.
- A `GAME_ID` regression test is deemed necessary (would require editing shared
  `tests/helpers.py`).

## Maintenance notes

- `if_exists="replace"` in the migration DROPS any index on `fantasy_logs`, and plan 012's
  UNIQUE `idx_fantasy_logs_player_date` **is now live** — Step 3 recreates it after migrating.
- Keep the incoming cast (Step 2) and any future schema change to these columns in lockstep
  with the stored affinity; a divergence re-opens the dedup-key-stability trap.
- The same latent float-affinity risk exists for any future `to_sql`-created table with
  blank numeric cells — prefer explicit `dtype=` on `to_sql` for ID columns generally.
