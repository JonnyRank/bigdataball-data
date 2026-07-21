# Plan 014: Normalize `fantasy_logs.PLAYER_ID` / `GAME_ID` to INTEGER

> **Executor instructions**: Follow this plan step by step. Run every verification command
> and confirm the expected result before moving to the next step. If anything in the "STOP
> conditions" section occurs, stop and report — do not improvise. When done, update the
> status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat dacd007..HEAD -- daily_fantasy_log_upload.py tests/helpers.py`
> Compare the "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (a mis-sequenced migration can re-insert every historical fantasy log — see
  the dedup-stability trap in Step 3)
- **Depends on**: none. **Order-independent from plan 012** — 012 indexes on `(PLAYER_ID,
  DATE)` and DATE (TEXT) is the discriminator, so a float `PLAYER_ID` does not affect that
  index. Either plan may land first.
- **Category**: data-integrity / type-hygiene
- **Planned at**: commit `dacd007`, 2026-07-21 (from the plan 012 review).
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

**`daily_fantasy_log_upload.py:250-252`** — the log insert, no cast, no `dtype`:

```python
truly_new_logs_df.to_sql(
    LOGS_TABLE_NAME, con=engine, if_exists="append", index=False
)
```

The dedup key is built just above (`:209-211`) as
`cleaned_data["PLAYER_ID"].astype(str) + "_" + cleaned_data["DATE"]`, and the DB snapshot key
at `:107-111`. With a float `PLAYER_ID` both sides produce `"12345.0"` — consistent today.

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
built (`:207`), drop rows missing an ID and cast the present ID column(s) to int. The one
ordering that matters: this must land **after** the `iloc[1:]` dummy-row drop (`:147`) — by
that point the fixture's placeholder `None` row is already gone, and `dropna(subset=id_cols)`
removes any remaining null-ID rows, so `.astype(int)` cannot hit a `NaN`:
```python
# Normalize ID columns to integers so fantasy_logs matches player_logs /
# player_absences (which store PLAYER_ID / GAME_ID as INTEGER). Rows missing
# an ID are not valid player-game logs -> drop them before casting.
id_cols = [c for c in ("PLAYER_ID", "GAME_ID") if c in cleaned_data.columns]
cleaned_data = cleaned_data.dropna(subset=id_cols)
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

Pass an explicit `dtype` on the log insert (`:250-252`) so the table is created with INTEGER
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

**Verify**: `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.

### Step 3: One-time migration of the existing `fantasy_logs` table

Create `patch_fantasy_id_types.py` (mirroring the existing `patch_absence_column_names.py`
precedent from plan 013 — read it for the path-resolution / engine idiom). It must:

1. Load the whole `fantasy_logs` table into pandas.
2. Drop rows with a null `PLAYER_ID` (or `GAME_ID` if present), then cast the present ID
   column(s) to int.
3. Write it back with `to_sql(LOGS_TABLE_NAME, engine, if_exists="replace", index=False,
   dtype={...Integer()...})` so the recreated table has INTEGER affinity.

Sketch:
```python
import pandas as pd
from sqlalchemy import create_engine, Integer
import os, paths

DB_PATH = os.path.join(paths.resolve_base_data_path(), "nba_fantasy_logs.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

df = pd.read_sql_table("fantasy_logs", engine)
id_cols = [c for c in ("PLAYER_ID", "GAME_ID") if c in df.columns]
df = df.dropna(subset=id_cols)
for c in id_cols:
    frac = df[c][df[c] % 1 != 0]
    if not frac.empty:
        raise ValueError(
            f"{c} has non-integer values (refusing to truncate): {frac.unique().tolist()}"
        )
    df[c] = df[c].astype(int)
df.to_sql(
    "fantasy_logs", engine, if_exists="replace", index=False,
    dtype={c: Integer() for c in id_cols},
)
print(f"Rewrote fantasy_logs: {len(df)} rows, {id_cols} cast to INTEGER.")
```

**Back up the DB first** (the same `.bak-*` habit `check_ingest_duplicates.py` uses), since
`if_exists="replace"` drops the table. If plan 012 has already added a unique index to
`fantasy_logs`, note that `if_exists="replace"` DROPS it — re-run the plan-012 index creation
(or `daily_fantasy_log_upload.py` once) afterward; call this out in the run log.

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
- Plan 012's index work — independent.

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

- `if_exists="replace"` in the migration DROPS any index on `fantasy_logs` (including plan
  012's unique index if that landed first) — recreate it after migrating.
- Keep the incoming cast (Step 2) and any future schema change to these columns in lockstep
  with the stored affinity; a divergence re-opens the dedup-key-stability trap.
- The same latent float-affinity risk exists for any future `to_sql`-created table with
  blank numeric cells — prefer explicit `dtype=` on `to_sql` for ID columns generally.
