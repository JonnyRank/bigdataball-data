# Plan 013: Ingest the DNP-DND-NWT sheet into a new `player_absences` table

> **Execution note (2026-07-18, PR #38)**: Step 1's verification found that
> `player_logs` stores `GAME_ID` as an **unpadded INTEGER** (pandas reads the
> box-score sheet's GAME-ID as int64 and `daily_player_upload.py` never
> converts it), not the zero-padded TEXT this plan's schema table and
> normalization snippets assume. Per Step 1's own fallback instruction
> ("match whatever `player_logs` actually does"), `player_absences.GAME_ID`
> was implemented as `astype(int)` — INTEGER, unpadded. Ignore the
> `zfill(10)` / TEXT references below; do not reintroduce padding.
>
> Also per review: the `ABSENCE_TYPE` classification compares
> `str(REASON).strip().upper()` against `COACH'S DECISION` (raw `REASON` is
> stored unchanged), so case/whitespace variants cannot silently
> miscategorize — design decision 5's exact-string comparison is superseded.
>
> **Post-merge correction (2026-07-18)**: the plan (and initial
> implementation) kept the sanitized sheet headers `GAME_DATE` and
> `PLAYER_NAME` as the table's column names. That breaks the repo-wide
> log-table convention — `player_logs`/`fantasy_logs` use `DATE` and
> `PLAYER` — and made `check_ingest_duplicates.py` silently report bogus
> duplicates (SQLite treats an unresolvable double-quoted identifier as a
> string literal). `absence_ingestion.py` now renames both at ingest, and
> `patch_absence_column_names.py` migrated the already-populated table.
> Read `GAME_DATE`/`PLAYER_NAME` below as `DATE`/`PLAYER`.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: Read the current `daily_player_upload.py` in
> full before editing. This plan references its structure (per-file loop,
> column sanitization, `log_key` dedup, dim_players learning, archive move).
> If the loop structure has materially changed since this plan was written,
> STOP and report the differences.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the daily ingestion path; mitigated by additive-only DB changes and tests)
- **Depends on**: 002 (test harness / `player_upload` fixture), 003 (cross-file dedup pattern — reuse it, do not reintroduce the bug it fixed)
- **Category**: feature

## Background

Every BigDataBall season player feed `.xlsx` contains a second sheet,
`DNP-DND-NWT`, listing one row per player per game **missed**, with a STATUS
(DNP = Did Not Play, DND = Did Not Dress, NWT = Not With Team) and a REASON
(e.g., COACH'S DECISION, INJURY/ILLNESS, REST, LEAGUE SUSPENSION).
`daily_player_upload.py` currently calls `pd.read_excel(file_path)` with no
`sheet_name`, so only the first sheet (box scores) is read and this data has
been silently discarded — including from every file already archived.

Profiling of the 2025-26 feed (06-13-2026 file, 6,076 absence rows):

- Columns: `GAME DATE` (datetime), `GAME-ID`, `TEAM`, `OPPONENT`,
  `PLAYER-ID`, `PLAYER NAME`, `STATUS`, `REASON`. No nulls. No duplicate
  (PLAYER-ID, GAME-ID) pairs within the file.
- The sheet is **cumulative for the whole season** and spans all season
  types (Regular Season, IST, Play-In, Playoffs). It has **no** season-type
  column of its own.
- STATUS distribution: DNP 5,010 / DND 989 / NWT 77.
- REASON distribution: COACH'S DECISION 4,903; INJURY/ILLNESS 1,059;
  NOT WITH TEAM 36; LEAGUE SUSPENSION 34; REST 29; PERSONAL 10;
  TURN TO COMPETITION RECONDITIONING 4; TEAM SUSPENSION 1.
- **Known source-data quirk**: 5 rows list a player as DNP who also has a
  real box-score line (with minutes) for the same game. These are
  BigDataBall errors. Policy: the box score wins, and the conflict is
  resolved **at ingest** — these rows are skipped (see design decision 6)
  so that downstream views and queries never need their own conflict check.
- 57 PLAYER-IDs in the sheet never appear in any box score all season, so
  they do not exist in `dim_players` yet. Decision: **learn them into
  `dim_players`** exactly like new box-score players.

## Design decisions (already made — do not revisit)

1. **Append-with-dedup**, following repo convention. Dedup key:
   `PLAYER_ID + "_" + GAME_ID`. (GAME_ID is preferred over DATE here because
   the sheet provides it natively and it is unambiguous.)
2. Unknown players are added to `dim_players` (`PLAYER_ID`, `PLAYER_NAME`),
   with `mappings.PLAYER_NAME_MAP` standardization applied first.
3. Shared ingestion logic lives in a new module `absence_ingestion.py`, used
   by BOTH the daily pipeline and a new one-shot backfill CLI
   `backfill_player_absences.py`.
4. Raw table only this phase. No views, no joins into `fantasy_averages`.
5. Store `STATUS` and `REASON` raw, plus a derived column `ABSENCE_TYPE`:
   - `REASON == "COACH'S DECISION"` → `ABSENCE_TYPE = 'DNP-CD'`
   - all other REASON values → `ABSENCE_TYPE = 'INJURY/ILLNESS/OTHER'`
6. **Conflict rows are filtered at ingest.** An absence row is skipped if a
   box-score row already exists in `player_logs` for the same
   (PLAYER_ID, GAME_ID). This resolves the box-score-wins policy once, at
   load time, so every future view/query can trust `player_absences`
   without re-checking. Ordering makes this safe: in the daily loop the
   box-score sheet is ingested before the absence sheet of the same file,
   and for backfill the historical box scores are already in the DB.

## Target schema

New table `player_absences` in `nba_fantasy_logs.db`:

| Column | Type | Notes |
|---|---|---|
| `GAME_DATE` | TEXT | `YYYY-MM-DD`, matching repo date convention |
| `GAME_ID` | TEXT | zero-padded to match `player_logs` format (verify in Step 1) |
| `TEAM` | TEXT | as provided (short name, e.g., "Houston") |
| `OPPONENT` | TEXT | as provided |
| `PLAYER_ID` | INTEGER | joins to `dim_players.PLAYER_ID` |
| `PLAYER_NAME` | TEXT | after `PLAYER_NAME_MAP` standardization |
| `STATUS` | TEXT | DNP / DND / NWT, raw |
| `REASON` | TEXT | raw |
| `ABSENCE_TYPE` | TEXT | derived, see above |

Let `pandas.to_sql` create the table on first append (repo convention); do
not hand-write DDL unless a type comes out wrong.

## Steps

### Step 1: Verify GAME_ID storage format in `player_logs`

The box-score sheet stores GAME-ID as a zero-padded text string
(`'0022500001'`), but pandas reads the DNP sheet's GAME-ID as `int64`
(dropping the leading zero). The two tables must agree so they can be joined
later.

```
python3 - <<'PY'
import os, sqlite3
# Point at the real DB or a copy; adjust path resolution as the repo does.
db = os.path.join(os.environ.get("BIGDATABALL_DATA_DIR", "Data"), "nba_fantasy_logs.db")
c = sqlite3.connect(db).cursor()
row = c.execute('SELECT "GAME_ID", typeof("GAME_ID") FROM player_logs LIMIT 1').fetchone()
print(row)
PY
```

**Verify**: note the value and its `typeof`. Expected: TEXT with a leading
zero (e.g., `('0022500001', 'text')`). Normalize the DNP sheet's GAME-ID to
this exact format in Step 2: `df["GAME_ID"] = df["GAME_ID"].astype(str).str.zfill(10)`.
If `player_logs` stores it differently (integer, or unpadded text), match
whatever `player_logs` actually does and note the deviation in the final
report. If the column doesn't exist in `player_logs` under that name, STOP.

### Step 2: Create `absence_ingestion.py`

New module at repo root. It must NOT resolve paths or create its own engine
at module level — it receives an `engine` so tests and the backfill CLI can
inject their own. Structure:

```python
# absence_ingestion.py
# Reads the DNP-DND-NWT sheet from a BigDataBall player-feed .xlsx and
# appends new rows to player_absences, learning unknown players into
# dim_players. Shared by daily_player_upload.py and backfill_player_absences.py.
import pandas as pd
from sqlalchemy import text
import mappings

ABSENCES_TABLE_NAME = "player_absences"
PLAYERS_TABLE_NAME = "dim_players"
ABSENCE_SHEET_NAME = "DNP-DND-NWT"
DNP_CD_REASON = "COACH'S DECISION"


def load_existing_absence_keys(engine):
    """Returns set of 'PLAYER_ID_GAMEID' keys already in player_absences.
    Empty set if the table doesn't exist yet (first run)."""
    try:
        df = pd.read_sql(
            f'SELECT DISTINCT "PLAYER_ID", "GAME_ID" FROM {ABSENCES_TABLE_NAME}',
            engine,
        )
        return set(df["PLAYER_ID"].astype(str) + "_" + df["GAME_ID"].astype(str))
    except Exception as e:
        if "no such table" in str(e):
            return set()
        raise


def ingest_absences(file_path, engine, existing_keys):
    """Process one file's DNP-DND-NWT sheet.

    Mutates existing_keys in place (adds keys it inserts) so the caller can
    process multiple cumulative files in one run without duplicates — same
    pattern as the plan-003 fix; the key set is initialized ONCE by the
    caller, never inside a per-file loop.

    Returns (inserted_count, sheet_found: bool).
    """
    try:
        df = pd.read_excel(file_path, sheet_name=ABSENCE_SHEET_NAME)
    except ValueError:
        # Sheet not present in this workbook (possible in older seasons).
        return 0, False

    df = df.dropna(how="all").copy()

    # Sanitize headers the same way daily_player_upload does, then map to
    # target names explicitly (don't rely on the sanitizer's hyphen handling).
    # Target: GAME_DATE, GAME_ID, TEAM, OPPONENT, PLAYER_ID, PLAYER_NAME,
    #         STATUS, REASON
    ...

    # Normalizations:
    #   GAME_DATE -> pd.to_datetime(...).dt.strftime("%Y-%m-%d")
    #   GAME_ID   -> astype(str).str.zfill(10)   # per Step 1 verification
    #   PLAYER_ID -> astype(int)
    #   PLAYER_NAME -> .replace(mappings.PLAYER_NAME_MAP)

    # Derived column:
    #   ABSENCE_TYPE = 'DNP-CD' where REASON == DNP_CD_REASON else 'INJURY/ILLNESS/OTHER'

    # Conflict filter (box score wins): load the set of
    #   PLAYER_ID + "_" + GAME_ID keys from player_logs and drop any absence
    #   row whose key is present. Print how many were skipped, e.g.:
    #   "  > Skipped N absence row(s) with a conflicting box-score record."
    # For efficiency, load only the two key columns:
    #   pd.read_sql('SELECT "PLAYER_ID", "GAME_ID" FROM player_logs', engine)
    # (Tolerate a missing player_logs table the same way
    #  load_existing_absence_keys does — treat as an empty key set.)

    # Dedup against existing_keys on PLAYER_ID + "_" + GAME_ID.
    # Learn new players into dim_players (reuse the daily_player_upload
    # pattern: read existing PLAYER_IDs, insert only unseen ones, renaming
    # PLAYER_NAME appropriately).
    # Append surviving rows to player_absences via to_sql(if_exists="append").
    # existing_keys.update(inserted keys)
    # return len(inserted), True
```

Implementation notes for the elided sections:

- Copy the exact header-sanitization snippet from `daily_player_upload.py`
  (uppercase, newlines/spaces → `_`, strip specials), then apply an explicit
  rename dict to reach the target column names. **First print the sanitized
  names on the real file** and write the rename dict against what you
  actually observe — do not guess how the sanitizer treats `PLAYER-ID`
  vs `GAME DATE`.
- Column order in the final DataFrame should match the Target schema table.
- Keep only the target columns before `to_sql` (drop the helper `log_key`).

**Verify**: `python3 -m py_compile absence_ingestion.py` → exit 0.

### Step 3: Wire into `daily_player_upload.py`

Inside `main()`:

1. After the existing box-score key preload and **before** the per-file
   loop, add:
   ```python
   import absence_ingestion
   existing_absence_keys = absence_ingestion.load_existing_absence_keys(engine)
   absences_count = 0
   ```
2. Inside the per-file loop, after the box-score processing succeeds and
   **before** the `os.replace()` archive move:
   ```python
   inserted, sheet_found = absence_ingestion.ingest_absences(
       file_path, engine, existing_absence_keys
   )
   if not sheet_found:
       print(f"  > WARNING: no '{absence_ingestion.ABSENCE_SHEET_NAME}' sheet in {file_name}; skipping absences.")
   else:
       print(f"  > Added {inserted} new absence rows to player_absences.")
   absences_count += inserted
   ```
   A missing sheet must be a warning, not an exception — the daily pipeline
   must not fail on a file that lacks the sheet.
3. Extend the function's return so the orchestrator can report the count.
   `main()` currently returns `(processed_count, overwritten_count)`;
   change it to return `(processed_count, overwritten_count, absences_count)`
   **and** update the caller in `daily_fantasy_log_upload.py`, which
   unpacks this tuple — keep its `isinstance(result, tuple)` fallback
   working. Add a line to the success-email body, e.g.
   `Absence Rows Processed: {absences_count}`.

**Verify**: `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` → exit 0.

### Step 4: Create `backfill_player_absences.py`

One-shot CLI at repo root. Usage:

```
python backfill_player_absences.py "path/to/2023-24 season file.xlsx" ["path/to/2024-25 file.xlsx" ...]
```

- `argparse` with one-or-more positional `files` arguments.
- Resolve `BASE_DATA_PATH` / DB path exactly the way `daily_player_upload.py`
  does (env override → G: mount → local `Data/`), create the engine, then:
  ```python
  keys = absence_ingestion.load_existing_absence_keys(engine)
  for f in files:
      inserted, sheet_found = absence_ingestion.ingest_absences(f, engine, keys)
      if not sheet_found:
          print(f"ERROR: no DNP-DND-NWT sheet in {f} — this season may predate the sheet.")
          sys.exit(1)   # loud failure is correct for backfill, unlike the daily path
      print(f"{f}: inserted {inserted} rows")
  ```
- Do NOT move or archive the input files — backfill reads archived files in
  place.
- Because BigDataBall files are cumulative per season, the correct input for
  each past season is the **latest** archived file of that season only.
  Print a reminder of this in the script's `--help` epilog.

Note for the user (include in final report): the current 2025-26 season does
NOT need the backfill script — the next daily run's cumulative file contains
the full season's absence sheet, so `player_absences` self-populates for
2025-26 automatically once Step 3 ships.

**Verify**: `python3 backfill_player_absences.py --help` → prints usage, exit 0.

### Step 5: Tests

Extend `tests/helpers.py` with a multi-sheet writer that produces a workbook
shaped like the real feed (box-score sheet first, `DNP-DND-NWT` second):

```python
def write_player_xlsx_with_absences(path, player_rows, absence_rows):
    """absence_rows: list of dicts with keys GAME DATE, GAME-ID, TEAM,
    OPPONENT, PLAYER-ID, PLAYER NAME, STATUS, REASON (raw feed headers)."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(player_rows, columns=["PLAYER_ID", "PLAYER", "DATE", "PTS"]).to_excel(
            writer, sheet_name="NBA-PLAYER", index=False)
        pd.DataFrame(absence_rows).to_excel(
            writer, sheet_name="DNP-DND-NWT", index=False)
```

New test file `tests/test_absence_ingestion.py` (reuse the `player_upload`
fixture). Required cases:

1. **Single file loads absences and learns unknown players** — an absence
   row whose PLAYER-ID has no box-score row ends up in both
   `player_absences` and `dim_players`.
2. **ABSENCE_TYPE derivation** — REASON `COACH'S DECISION` → `DNP-CD`;
   REASON `REST` (and one other) → `INJURY/ILLNESS/OTHER`.
3. **Rerun with the same file inserts no duplicates** (dedup vs DB).
4. **Two cumulative files in one run insert no duplicates** (dedup vs
   in-memory key set — the plan-003 pattern).
5. **Missing sheet doesn't crash the daily pipeline** — a workbook written
   with `write_player_xlsx` (box scores only) still processes and archives;
   `player_absences` row count unchanged.
6. **Conflict rows are excluded** — a player with BOTH a box-score row and
   an absence row for the same game ends up in `player_logs` only;
   `player_absences` does not contain the row (box-score-wins at ingest).
   Also assert the non-conflicting absence rows in the same file ARE
   inserted (the filter must drop rows, not files).
7. **Name standardization** — a PLAYER NAME present in `PLAYER_NAME_MAP`
   is stored standardized in both `player_absences` and `dim_players`.
8. **GAME_ID normalization** — an integer GAME-ID like `22500001` is stored
   as the zero-padded text form matching `player_logs` (per Step 1).

**Verify**: `python3 -m pytest tests/ -q` → all tests pass, including the
pre-existing suite.

### Step 6: End-to-end smoke test on the real file

Using a throwaway `BIGDATABALL_DATA_DIR` with a copy of (or empty)
database, drop the real `06-13-2026-nba-season-player-feed.xlsx` into
`Daily_Player_Logs/` and run `python3 daily_player_upload.py`. Then:

```
python3 - <<'PY'
import os, sqlite3
db = os.path.join(os.environ["BIGDATABALL_DATA_DIR"], "nba_fantasy_logs.db")
c = sqlite3.connect(db).cursor()
n = c.execute("SELECT COUNT(*) FROM player_absences").fetchone()[0]
mc = dict(c.execute("SELECT ABSENCE_TYPE, COUNT(*) FROM player_absences GROUP BY 1").fetchall())
orphans = c.execute("""SELECT COUNT(*) FROM player_absences a
    LEFT JOIN dim_players d ON a.PLAYER_ID = d.PLAYER_ID WHERE d.PLAYER_ID IS NULL""").fetchone()[0]
print(n, mc, orphans)
PY
```

**Verify**: row count = **6,071** (6,076 in the sheet minus the 5
box-score conflicts, all of which are DNP / COACH'S DECISION); ABSENCE_TYPE
splits **4,898** (`DNP-CD`) / **1,173** (`INJURY/ILLNESS/OTHER`); orphans =
0 (every absence PLAYER_ID exists in dim_players). The run log should show
the "Skipped 5 absence row(s)" message. Running `daily_player_upload.py` a
second time with the same file inserts 0 new absence rows.

Additionally, confirm zero conflicts survived:

```
SELECT COUNT(*) FROM player_absences a
JOIN player_logs p ON a.PLAYER_ID = p.PLAYER_ID AND a.GAME_ID = p.GAME_ID;
```

**Verify**: returns 0.

### Step 7: Documentation and housekeeping

- Add `player_absences` to the schema section of
  `.github/copilot-instructions.md` and `docs/codebase/` schema/architecture
  docs (wherever tables are listed), including the ABSENCE_TYPE mapping and
  the 5-conflict-rows / box-score-wins policy note.
- Add `absence_ingestion.py` and `backfill_player_absences.py` to
  `docs/codebase/STRUCTURE.md`.
- Add this plan's row to `plans/README.md` and mark it done.

## STOP conditions

- Sanitized/renamed column names on the real file don't match the target
  schema after writing the rename dict (report the observed names).
- `player_logs` has no `GAME_ID` column, or its storage format can't be
  matched cleanly (Step 1).
- Any pre-existing test fails after the Step 3 wiring (especially the
  return-tuple change rippling into `daily_fantasy_log_upload.py`).
- The Step 6 smoke test counts don't match the expected 6,071 /
  4,898 / 1,173 / 0 figures, or the conflict-join query returns nonzero.
- A backfill input file for 2023-24 or 2024-25 lacks the `DNP-DND-NWT`
  sheet — report it; do not fabricate absence data from box-score gaps.

## Out of scope (explicitly)

- Delete-and-replace ingestion refactor (future consideration, all tables).
- Any views over `player_absences` (participation view, games-missed
  counts, joining absences into `fantasy_averages`).
- Season-type attribution for absence rows (derivable later via GAME_ID
  join to `player_logs`).
- **Late-correction cleanup**: if BigDataBall ever adds a box score in a
  *later* file for a game whose absence row was already loaded, a conflict
  could enter the table after the fact (the ingest filter only sees box
  scores present at load time). Deliberately out of scope for now to keep
  the table pure-append; if it ever occurs, the fix is a single
  post-ingest `DELETE FROM player_absences WHERE (PLAYER_ID, GAME_ID) IN
  (SELECT PLAYER_ID, GAME_ID FROM player_logs)`. The Step 6 conflict-join
  query doubles as the detection check.
