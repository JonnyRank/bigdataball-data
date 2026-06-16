# Plan 006: Extract the triplicated DraftKings load + fuzzy-match logic into one tested module

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- export_slate_averages_vw.py export_playoffs_slate_averages_vw.py export_slate_averages_csv.py`
> Plan 005 changes the `BASE_DATA_PATH` line inside these functions; the DK-load and
> matching code this plan extracts is separate. Compare the "Current state" excerpts
> against the live code; on a mismatch in the matching code, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 002 (pytest). Recommended after 005 (same files).
- **Category**: tech-debt
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

Three export scripts each re-implement the same DraftKings pipeline preamble: detect the
header row in `~/Downloads/DKEntries.csv`, read it, extract unique player names, fetch the
valid DB player list, apply `mappings.PLAYER_NAME_MAP`, and fuzzy-match each DK name to the
DB with a hardcoded score threshold of 90. A change to the matching rule (threshold,
mapping order, header detection) today requires editing three places and they can drift.
Extracting the logic into one module removes the duplication and — because the matching
function is pure — lets us add the repo's first unit tests for the matching rule.

## Current state

The near-identical code appears in:
- `export_slate_averages_vw.py:37-103` (header detect, load, fetch, match, build name string)
- `export_playoffs_slate_averages_vw.py:37-103` (same, but queries `vw_player_averages_playoffs`)
- `export_slate_averages_csv.py:39-119` (same, plus it prints mapped names)

The shared logic, from `export_slate_averages_vw.py`:

Header detection (lines 39-46):
```python
    header_row_index = 0
    with open(DK_FILE_PATH, "r") as f:
        lines = f.readlines()
    for i, line in enumerate(lines[:50]):
        if "Position" in line and "Name + ID" in line:
            header_row_index = i
            break
```

Load + extract names (lines 50-58):
```python
    dk_df = pd.read_csv(DK_FILE_PATH, header=header_row_index)
    if "Name" not in dk_df.columns:
        print("ERROR: Could not find 'Name' column.")
        return []
    dk_df = dk_df.dropna(subset=["Name"])
    dk_names = dk_df["Name"].unique().tolist()
```

Match (lines 74-97), using `from thefuzz import process` and `mappings.PLAYER_NAME_MAP`:
```python
    for dk_name in dk_names:
        if dk_name in mappings.PLAYER_NAME_MAP:
            dk_name = mappings.PLAYER_NAME_MAP[dk_name]
        match, score = process.extractOne(dk_name, valid_db_names)
        if score >= 90:
            final_names_to_query.append(match)
        else:
            unmatched_names.append(f"{dk_name} (Best match: {match}, Score: {score})")
    ...
    final_names_to_query = list(set(final_names_to_query))
```

Then each script builds `sql_names_string` from `final_names_to_query`:
```python
    formatted_names = [name.replace("'", "''") for name in final_names_to_query]
    sql_names_string = "', '".join(formatted_names)
```

## The extraction

Create `dk_matching.py` with three pure functions matching the current behavior exactly:

```python
import os

import mappings
from thefuzz import process

DK_FILENAME = "DKEntries.csv"
MATCH_THRESHOLD = 90


def find_dk_file_path():
    """Path to DKEntries.csv in the user's Downloads folder."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(downloads, DK_FILENAME)


def load_dk_names(dk_file_path):
    """Detect the header row and return the list of unique player names.

    Returns None if the file is missing or has no 'Name' column (callers treat
    None as 'abort this pipeline' — matching the current early-return behavior).
    """
    import pandas as pd

    if not os.path.exists(dk_file_path):
        print(f"ERROR: Could not find file at {dk_file_path}")
        return None

    print(f"Reading file: {dk_file_path}")
    header_row_index = 0
    with open(dk_file_path, "r") as f:
        lines = f.readlines()
    for i, line in enumerate(lines[:50]):
        if "Position" in line and "Name + ID" in line:
            header_row_index = i
            break

    dk_df = pd.read_csv(dk_file_path, header=header_row_index)
    if "Name" not in dk_df.columns:
        print("ERROR: Could not find 'Name' column.")
        return None
    dk_df = dk_df.dropna(subset=["Name"])
    return dk_df["Name"].unique().tolist()


def match_names(dk_names, valid_db_names, threshold=MATCH_THRESHOLD):
    """Map DK names to DB names. Returns (matched_db_names, unmatched_descriptions).

    matched_db_names is de-duplicated (order not guaranteed), matching today's
    `list(set(...))`. Applies mappings.PLAYER_NAME_MAP before fuzzy matching.
    """
    matched = []
    unmatched = []
    # Guard: process.extractOne raises on an empty choice list. If the DB/view returned
    # no players (a fresh DB, or an out-of-season playoffs view), treat every DK name as
    # unmatched rather than crashing the pipeline. This is a deliberate robustness
    # improvement over the original inline code (which would crash here).
    if not valid_db_names:
        unmatched = [
            f"{mappings.PLAYER_NAME_MAP.get(n, n)} (Best match: None, Score: 0)"
            for n in dk_names
        ]
        return [], unmatched
    for dk_name in dk_names:
        if dk_name in mappings.PLAYER_NAME_MAP:
            dk_name = mappings.PLAYER_NAME_MAP[dk_name]
        match, score = process.extractOne(dk_name, valid_db_names)
        if score >= threshold:
            matched.append(match)
        else:
            unmatched.append(f"{dk_name} (Best match: {match}, Score: {score})")
    return list(set(matched)), unmatched


def to_sql_in_list(names):
    """Single-quote-escape and join names for a SQL IN (...) clause."""
    formatted = [name.replace("'", "''") for name in names]
    return "', '".join(formatted)
```

This preserves every observable behavior: header detection, the `Name`-column guard,
mapping-before-fuzzy, the `>= 90` threshold, the de-dup via `set`, and the SQL escaping.
The one **intentional** addition is the empty-`valid_db_names` guard in `match_names`
(the original inline code would raise from `process.extractOne` on an empty choice list —
e.g. a fresh DB or an out-of-season playoffs view); the guard returns all DK names as
unmatched instead of crashing.

## Commands you will need

| Purpose      | Command                                                              | Expected on success |
|--------------|----------------------------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile dk_matching.py export_slate_averages_vw.py export_playoffs_slate_averages_vw.py export_slate_averages_csv.py` | exit 0 |
| Run tests    | `python3 -m pytest -q`                                                | all pass            |

## Scope

**In scope**:
- `dk_matching.py` (create)
- `export_slate_averages_vw.py`, `export_playoffs_slate_averages_vw.py`,
  `export_slate_averages_csv.py` — replace the inlined load/match/escape code with calls
  to `dk_matching`.
- `tests/test_dk_matching.py` (create)

**Out of scope** (do NOT change behavior of):
- The early-return contract: where a script currently `return []` (vw scripts) or
  `return` (csv script) on a missing file / missing `Name` column, keep returning the
  same value when `load_dk_names` returns `None`.
- The view/query SQL bodies (season filters, column lists, `ORDER BY`) — untouched.
- The warning-printing blocks — you may keep them in the scripts (they iterate
  `unmatched`); do not move them into `dk_matching`.
- `mappings.py` and the `>= 90` threshold value.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Extract shared DraftKings matching into dk_matching module`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `dk_matching.py`

Create the module exactly as in "The extraction" above.

**Verify**: `python3 -c "import dk_matching"` → exit 0 (requires deps installed).

### Step 2: Refactor `export_slate_averages_vw.py`

Replace the path/load/match/escape preamble so the function becomes:
- `DK_FILE_PATH = dk_matching.find_dk_file_path()`
- `dk_names = dk_matching.load_dk_names(DK_FILE_PATH)`; `if dk_names is None: return []`
- fetch `valid_db_names` from `vw_player_averages_regular_season` (unchanged)
- `final_names_to_query, unmatched_names = dk_matching.match_names(dk_names, valid_db_names)`
- keep the existing "WARNING: N players ... could not be matched" print loop over `unmatched_names`
- `sql_names_string = dk_matching.to_sql_in_list(final_names_to_query)`
- the rest of the view-creation code is unchanged.

Add `import dk_matching` at the top. Keep returning `unmatched_names` at the end.

**Verify**: `python3 -m py_compile export_slate_averages_vw.py` → exit 0;
`grep -c "process.extractOne" export_slate_averages_vw.py` → `0` (logic moved out).

### Step 3: Refactor `export_playoffs_slate_averages_vw.py`

Same as Step 2, but it fetches `valid_db_names` from `vw_player_averages_playoffs` and
returns `unmatched_names` (the orchestrator discards it per plan 004 — that's fine).

**Verify**: `python3 -m py_compile export_playoffs_slate_averages_vw.py` → exit 0;
`grep -c "process.extractOne" export_playoffs_slate_averages_vw.py` → `0`.

### Step 4: Refactor `export_slate_averages_csv.py`

Same pattern. This script additionally printed `> Mapped 'X' -> 'Y'` lines during
matching. `match_names` does not print those. To preserve user-visible output with
minimal scope, after calling `match_names` you may keep a short loop that is purely
cosmetic, **or** drop the per-name "Mapped" prints (they are debug chatter, not
contractual). Either is acceptable; do not change which names end up matched. Keep this
script's early `return` (no value) when `load_dk_names` returns `None`.

**Verify**: `python3 -m py_compile export_slate_averages_csv.py` → exit 0;
`grep -c "process.extractOne" export_slate_averages_csv.py` → `0`.

### Step 5: Unit-test the matching logic

Create `tests/test_dk_matching.py`:
```python
import dk_matching


def test_exact_match_is_kept():
    matched, unmatched = dk_matching.match_names(["LeBron James"], ["LeBron James", "Stephen Curry"])
    assert matched == ["LeBron James"]
    assert unmatched == []


def test_mapping_applied_before_fuzzy():
    # mappings.PLAYER_NAME_MAP maps "GG Jackson" -> "Gregory Jackson"
    matched, unmatched = dk_matching.match_names(["GG Jackson"], ["Gregory Jackson"])
    assert matched == ["Gregory Jackson"]
    assert unmatched == []


def test_below_threshold_is_unmatched():
    matched, unmatched = dk_matching.match_names(["Zzqx Nobody"], ["LeBron James"])
    assert matched == []
    assert len(unmatched) == 1
    assert "Zzqx Nobody" in unmatched[0]


def test_empty_db_list_does_not_crash():
    # On a fresh DB / out-of-season view the choice list is empty; must not raise.
    matched, unmatched = dk_matching.match_names(["LeBron James"], [])
    assert matched == []
    assert len(unmatched) == 1
    assert "LeBron James" in unmatched[0]


def test_sql_in_list_escapes_quotes():
    assert dk_matching.to_sql_in_list(["O'Neal", "Curry"]) == "O''Neal', 'Curry"
```

**Verify**: `python3 -m pytest -q tests/test_dk_matching.py` → passes.

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

- New `tests/test_dk_matching.py` covers: exact match retained, mapping applied before
  fuzzy match, sub-threshold name reported as unmatched, the empty-DB-list guard (no
  crash), and SQL quote-escaping.
- Existing 002–004 tests confirm the orchestrator still runs (the export functions are
  stubbed there, so this refactor doesn't affect them — that's expected).
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `dk_matching.py` exists with `load_dk_names`, `match_names`, `to_sql_in_list`, `find_dk_file_path`.
- [ ] `grep -rc "process.extractOne" export_*.py` shows `0` in all three export scripts.
- [ ] `python3 -m py_compile *.py` exits 0.
- [ ] `python3 -m pytest -q` exits 0; `tests/test_dk_matching.py` passes.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 006 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- A script's early-return value can't be preserved (e.g. the vw scripts must return `[]`
  but you can only return `None`) — report; do not change the orchestrator's expectations.
- The fuzzy-match results differ from the originals for a realistic name set — the
  threshold or mapping order was altered; re-check `match_names` against "Current state".
- `thefuzz`/`RapidFuzz` is not installed — `pip install -r requirements.txt` first; if it
  still fails, report.

## Maintenance notes

- A reviewer should confirm the three scripts produce the same matched/unmatched sets as
  before (no threshold or ordering change) and that SQL escaping is unchanged.
- Future: the threshold `90` is now a single named constant `MATCH_THRESHOLD` — tune it
  in one place. If header detection needs to handle a new DK export format, change only
  `load_dk_names`.
