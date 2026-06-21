# Plan 007: Centralize the hardcoded season filters so the yearly rollover is a one-place edit

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- export_slate_averages_vw.py export_playoffs_slate_averages_vw.py export_slate_averages_csv.py`
> Plans 005/006 touch these files. The season-filter string literals this plan replaces
> are in the SQL bodies. Compare the "Current state" excerpts against the live code; on a
> mismatch in the SQL filters, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: MED
- **Depends on**: 002 (pytest). Recommended after 006 (same files).
- **Category**: tech-debt
- **Planned at**: commit `a852503`, 2026-06-21 (refreshed for plan 005's merge `#24`; original `5576703` 2026-06-16). Plan 005 (DONE) removed each export's inline path block, shifting the SQL line numbers below up by a few lines. The season literals and their values are **unchanged** — only the cited line numbers were refreshed.

## Why this matters

The NBA season strings are hardcoded inline in the export SQL, and the filters differ per
view: the full slate spans two seasons, the L30 view is the current season only, and the
playoffs view uses a single playoff year. `CLAUDE.md` flags this as a gotcha that must be
"updated at the start of a new NBA season" across multiple files. Centralizing the season
values into named constants makes the yearly rollover a single, obvious edit and removes
the risk of updating one view but not another.

## Current state

The season literals, by file:

- `export_slate_averages_vw.py`:
  - `vw_daily_slate`: `WHERE SEASON in ('2024-25', '2025-26')` (line ~124)
  - `vw_daily_slate_l30`: `WHERE SEASON = '2025-26'` (line ~168)
- `export_playoffs_slate_averages_vw.py`:
  - `vw_daily_slate_playoffs`: `WHERE SEASON = '2026'` (line ~124)
- `export_slate_averages_csv.py`:
  - main CSV query: `WHERE SEASON in ('2024-25', '2025-26')` (line ~124)
  - L30 CSV query: `WHERE SEASON = '2025-26'` (line ~160)

So three distinct values are in play:
- **SLATE_SEASONS** = the multi-season span: `('2024-25', '2025-26')`
- **L30_SEASON** = the current regular season: `'2025-26'`
- **PLAYOFFS_SEASON** = the current playoff year: `'2026'`

These are interpolated into f-string SQL via `IN ('...')` and `= '...'`.

## The change

Add a small `seasons.py` module (or a section in `config.py` — use a new module to keep
`config.py`'s Drive/email concerns separate):

```python
# Season filters for the slate views and exports.
# Update these THREE values at the start of each NBA season; nothing else changes.
SLATE_SEASONS = ("2024-25", "2025-26")  # multi-season span for vw_daily_slate + main CSV
L30_SEASON = "2025-26"                   # current regular season for L30 views/CSVs
PLAYOFFS_SEASON = "2026"                 # current playoff year for vw_daily_slate_playoffs


def slate_seasons_sql():
    """Render SLATE_SEASONS as the body of a SQL IN (...) list, e.g. "'2024-25', '2025-26'"."""
    return ", ".join(f"'{s}'" for s in SLATE_SEASONS)
```

Then each SQL string sources its season filter from these constants instead of inline
literals. Because the values are trusted, hardcoded season constants (not user input),
interpolating them into the SQL keeps the existing pattern and risk profile.

## Commands you will need

| Purpose      | Command                                                              | Expected on success |
|--------------|----------------------------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile seasons.py export_slate_averages_vw.py export_playoffs_slate_averages_vw.py export_slate_averages_csv.py` | exit 0 |
| Run tests    | `python3 -m pytest -q`                                                | all pass            |
| Find literals| `grep -rn "2024-25\|2025-26\|'2026'" export_*.py`                     | no matches after change |

## Scope

**In scope**:
- `seasons.py` (create)
- `export_slate_averages_vw.py`, `export_playoffs_slate_averages_vw.py`,
  `export_slate_averages_csv.py` — replace inline season literals with `seasons.*`.
- `tests/test_seasons.py` (create)

**Out of scope** (do NOT touch):
- `create_summary_tables.py` — its season *parsing* (deriving `SEASON_KEY` from
  `SEASON_SEGMENT`) is computed from data, not a hardcoded filter; leave it.
- The view names, column lists, `ORDER BY`, and `CAST` expressions in the SQL.
- `config.py`.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Centralize season filters into seasons module`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `seasons.py`

Create the module as in "The change" above.

**Verify**:
- `python3 -c "import seasons; print(seasons.slate_seasons_sql())"` → `'2024-25', '2025-26'`
- `python3 -c "import seasons; print(seasons.L30_SEASON, seasons.PLAYOFFS_SEASON)"` → `2025-26 2026`

### Step 2: Update `export_slate_averages_vw.py`

Add `import seasons`. In the `vw_daily_slate` SQL, replace
`WHERE SEASON in ('2024-25', '2025-26')` with `WHERE SEASON in ({seasons.slate_seasons_sql()})`
(the surrounding string is already an f-string — confirm the `f"""` prefix is present;
it is). In the `vw_daily_slate_l30` SQL, replace `WHERE SEASON = '2025-26'` with
`WHERE SEASON = '{seasons.L30_SEASON}'`.

**Verify**: `python3 -m py_compile export_slate_averages_vw.py` → exit 0;
`grep -c "2025-26" export_slate_averages_vw.py` → `0`.

### Step 3: Update `export_playoffs_slate_averages_vw.py`

Add `import seasons`. Replace `WHERE SEASON = '2026'` with
`WHERE SEASON = '{seasons.PLAYOFFS_SEASON}'` (confirm the SQL is an f-string).

**Verify**: `python3 -m py_compile export_playoffs_slate_averages_vw.py` → exit 0;
`grep -c "'2026'" export_playoffs_slate_averages_vw.py` → `0`.

### Step 4: Update `export_slate_averages_csv.py`

Add `import seasons`. Replace the main query's `WHERE SEASON in ('2024-25', '2025-26')`
with `WHERE SEASON in ({seasons.slate_seasons_sql()})`, and the L30 query's
`WHERE SEASON = '2025-26'` with `WHERE SEASON = '{seasons.L30_SEASON}'`.

**Verify**: `python3 -m py_compile export_slate_averages_csv.py` → exit 0;
`grep -c "2024-25\|2025-26" export_slate_averages_csv.py` → `0`.

### Step 5: Add a test for the SQL rendering helper

Create `tests/test_seasons.py`:
```python
import seasons


def test_slate_seasons_sql_renders_quoted_csv():
    # Exactly the body that goes inside SQL IN (...)
    assert seasons.slate_seasons_sql() == "'2024-25', '2025-26'"


def test_constants_have_expected_shapes():
    assert isinstance(seasons.SLATE_SEASONS, tuple) and len(seasons.SLATE_SEASONS) >= 1
    assert "-" in seasons.L30_SEASON          # regular-season form 'YYYY-YY'
    assert seasons.PLAYOFFS_SEASON.isdigit()  # playoff year 'YYYY'
```

**Verify**: `python3 -m pytest -q tests/test_seasons.py` → passes.

### Step 6: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

- `tests/test_seasons.py` locks the `IN (...)` rendering and the constant shapes.
- A reviewer can confirm the generated SQL is unchanged by eye: the rendered string for
  `slate_seasons_sql()` is byte-identical to the old literal `'2024-25', '2025-26'`.
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `seasons.py` exists with `SLATE_SEASONS`, `L30_SEASON`, `PLAYOFFS_SEASON`, `slate_seasons_sql()`.
- [ ] `grep -rn "'2024-25'\|'2025-26'\|'2026'" export_*.py` returns no matches (all sourced from `seasons`).
- [ ] `python3 -m py_compile *.py` exits 0.
- [ ] `python3 -m pytest -q` exits 0; `tests/test_seasons.py` passes.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 007 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- A target SQL string is **not** an f-string (no `f"""` prefix) — interpolating
  `{seasons...}` would emit a literal; report so the string can be converted carefully.
- `grep` finds a season literal in a file not listed here — report; don't expand scope.
- The rendered `IN (...)` body differs from `'2024-25', '2025-26'` (spacing/quoting) —
  fix `slate_seasons_sql()` to match exactly before proceeding.

## Maintenance notes

- A reviewer should diff the generated SQL mentally: only the season filter source
  changed, not the values.
- The annual rollover is now: edit the three constants in `seasons.py`. Note the L30 and
  playoffs values are deliberately separate from the two-season span — keep that
  distinction when rolling over.
