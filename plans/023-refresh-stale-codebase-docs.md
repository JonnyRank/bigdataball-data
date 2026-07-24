# Plan 023: Correct the stale facts in `docs/codebase/STACK.md` and `TESTING.md`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ba82f6a..HEAD -- docs/codebase/STACK.md docs/codebase/TESTING.md .github/workflows/test.yml pyproject.toml tests/`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live files before proceeding; on a mismatch, treat
> it as a STOP condition — the corrected values below may themselves be stale.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `ba82f6a`, 2026-07-24
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/66

## Why this matters

`CLAUDE.md` opens with "Use the codebase docs for details instead of
re-discovering the repo each time" and points every agent and new contributor at
`docs/codebase/`. Two of those files now assert things that are **false**, and
they're the two an executor is most likely to trust without checking:

- `STACK.md` says CI pins **Python 3.11** and that no `python_requires` floor is
  declared. CI has run **3.13** since the plan-009 src-layout merge, and
  `pyproject.toml` declares `requires-python = ">=3.11"`.
- `TESTING.md`'s test inventory is missing **two whole test modules**
  (`test_create_summary_tables.py`, `test_patch_fantasy_id_types.py`), undercounts
  a third by 4 tests, and lists `create_summary_tables.py` as untested with
  "(plan 011, TODO)" — plan 011 is **DONE** and those tests have existed since
  2026-07-23.

The concrete cost: an agent reading `TESTING.md` concludes `create_summary_tables.py`
has no coverage and either writes duplicate tests or treats a refactor there as
unguarded. An agent reading `STACK.md` targets 3.11-only syntax, or believes there
is no enforced floor to respect. The inventory numbers also no longer sum to the
suite total (56 vs. the actual 68), which is the tell that the file drifted.

This is a docs-only change. No source code, no tests, no behavior.

## Current state

### File 1 — `docs/codebase/STACK.md`

Line 5 (the `## Language & Runtime` section), verbatim:

```
- **Language:** Python. Local development uses **3.13.3** (the git-ignored `venv/`); CI pins **3.11** (`.github/workflows/test.yml:18`). No `python_requires` is declared in-repo, so there is no enforced floor — code must remain compatible across 3.11–3.13.
```

Line 6, verbatim:

```
- **Platform:** Primary development/runtime environment is Windows 11 (paths like `G:\My Drive\...` are hardcoded; see `config.py:7`). CI runs on `ubuntu-latest` (`.github/workflows/test.yml:10`).
```

Line 49 (in the `## Evidence` list), verbatim:

```
- `.github/workflows/test.yml` (Python 3.11, ubuntu-latest, install + pytest)
```

Line 53 (also `## Evidence`), verbatim:

```
- `pyproject.toml` (setuptools src-layout manifest; no `[tool.ruff]` or runtime deps declared)
```

**The ground truth** — `.github/workflows/test.yml` as it exists today:

```yaml
jobs:                       # line 11
  pytest:                   # line 12
    runs-on: ubuntu-latest  # line 13
    steps:                  # line 14
      - name: Checkout repository
        uses: actions/checkout@v6

      - name: Set up Python          # line 18
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"     # line 21

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
          pip install -e .

      - name: Run tests
        run: python -m pytest -q
```

**The ground truth** — `pyproject.toml` as it exists today:

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "bigdataball"
version = "0.1.0"
description = "NBA daily fantasy sports (DFS) data pipeline."
requires-python = ">=3.11"

[tool.setuptools.packages.find]
where = ["src"]
```

So: CI Python is **3.13** (`test.yml:21`), `runs-on: ubuntu-latest` is at
**`test.yml:13`** (not `:10`), and a `requires-python = ">=3.11"` floor **is**
declared. The "no `[tool.ruff]` section" half of line 53 is still accurate today.

### File 2 — `docs/codebase/TESTING.md`

The `## Organization` tree, lines 20–34, verbatim:

```
tests/
├── __init__.py                       # makes `from tests.helpers import ...` work
├── conftest.py                       # `player_upload` fixture
├── helpers.py                        # synthetic .xlsx writers
├── test_daily_player_upload.py       # 6  — box-score ingestion behavior
├── test_daily_fantasy_log_upload.py  # 6  — fantasy-log ingestion (inline loop)
├── test_absence_ingestion.py         # 11 — DNP-DND-NWT sheet → player_absences
├── test_check_ingest_duplicates.py   # 10 — dedup detection/removal
├── test_dk_matching.py               # 8  — DraftKings load + fuzzy match helper
├── test_seed_map_teams.py            # 9  — map_teams seeding
├── test_seasons.py                   # 3  — season-filter constants/SQL
├── test_paths.py                     # 2  — resolve_base_data_path precedence
└── test_orchestrator_warnings.py     # 1  — unmatched-players worklist warning
```

Those counts sum to **56**. The suite is **68**.

Line 39, verbatim:

```
- **`test_daily_fantasy_log_upload.py`** (6): single-file fantasy-log load + player learning, name standardization, `DRAFTKINGS1` column drop/rename, ISO date handling (plan 010). Uses a module-scoped `autouse` fixture that no-ops `email_notifier.send_email_alert` so `main()`-driving tests don't attempt a real SMTP send.
```

Line 58 (in `## Gaps / Not Covered`), verbatim:

```
- **No tests** for `create_summary_tables.py` (plan 011, TODO), the view-building bodies of the three `export_*` scripts (their DK-matching helper *is* tested via `test_dk_matching.py`), `drive_ingestion.py`/`auth_manager.py` (Google Drive), `email_notifier.py`, or `run_db_patch.py`/`verify_db_patch.py`.
```

Line 61, verbatim:

```
- **Broadening coverage to the summary/export scripts stays a near-term goal** (plan 011). The `player_upload` env-seam fixture pattern (fresh import under `BIGDATABALL_DATA_DIR`, dispose engine on teardown) is the template to extend; the summary/export scripts additionally need a seeded `map_teams` table (now easy via `seed_map_teams.py`) and the player-average views in place.
```

**The ground truth** — actual per-file test counts, from
`python -m pytest -q --collect-only`:

| File | Tests |
|------|-------|
| `tests/test_absence_ingestion.py` | 11 |
| `tests/test_daily_fantasy_log_upload.py` | **10** |
| `tests/test_check_ingest_duplicates.py` | 10 |
| `tests/test_seed_map_teams.py` | 9 |
| `tests/test_dk_matching.py` | 8 |
| `tests/test_daily_player_upload.py` | 6 |
| `tests/test_create_summary_tables.py` | **5** (missing from the doc) |
| `tests/test_seasons.py` | 3 |
| `tests/test_patch_fantasy_id_types.py` | **3** (missing from the doc) |
| `tests/test_paths.py` | 2 |
| `tests/test_orchestrator_warnings.py` | 1 |
| **Total** | **68** |

The test names in the three affected modules (use these to write accurate
descriptions — do not invent coverage claims):

```
test_daily_fantasy_log_upload.py::test_dedup_across_files_in_one_run
test_daily_fantasy_log_upload.py::test_unique_index_exists_on_fantasy_logs
test_daily_fantasy_log_upload.py::test_single_file_loads_logs_and_learns_players
test_daily_fantasy_log_upload.py::test_player_name_standardization_applied
test_daily_fantasy_log_upload.py::test_unwanted_columns_are_dropped
test_daily_fantasy_log_upload.py::test_date_stored_as_iso_format
test_daily_fantasy_log_upload.py::test_player_id_stored_as_integer
test_daily_fantasy_log_upload.py::test_rerun_same_file_no_duplicates_after_int_cast
test_daily_fantasy_log_upload.py::test_fractional_player_id_is_rejected_not_truncated
test_daily_fantasy_log_upload.py::test_missing_player_id_row_dropped_counted_and_surfaced

test_create_summary_tables.py::test_missing_tables_returns_false
test_create_summary_tables.py::test_basic_aggregation_creates_fantasy_averages
test_create_summary_tables.py::test_season_type_classification
test_create_summary_tables.py::test_l30fppm_excludes_old_games
test_create_summary_tables.py::test_run_summary_pipeline_creates_views

test_patch_fantasy_id_types.py::test_migration_flips_affinity_preserves_data_and_index
test_patch_fantasy_id_types.py::test_migration_is_idempotent_and_skips_backup
test_patch_fantasy_id_types.py::test_migration_rejects_fractional_id
```

For plan context that the corrected text should reflect (all verified in
`plans/README.md`): plan **011** (tests for `create_summary_tables.py`) is **DONE**;
plan **014** (INTEGER ID normalization, which added `test_patch_fantasy_id_types.py`
and the 4 extra fantasy-upload tests) is **DONE**; plan **019** (tests for the three
`export_*` view-builders) is the still-open **TODO** that should replace the stale
"plan 011" pointer on line 61.

### Conventions that apply

- These docs are **descriptive, evidence-backed reference files**, not a
  changelog. Every claim carries a `file:line` or `file` citation. Match that
  style: state the current fact and cite where it can be checked. Do **not** add
  "changed from X to Y" or dated "as of" notes to `STACK.md`/`TESTING.md` — the
  git history is the changelog.
- Keep the existing heading structure, bullet order, table alignment, and the
  ASCII tree characters (`├──`, `└──`) exactly as they are.
- Plan references in these docs are written as bare `plan NNN` / `(plan NNN)` —
  keep that form, don't turn them into links.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Per-file test counts | `python -m pytest -q --collect-only \| grep "::" \| sed 's/::.*//' \| sort \| uniq -c \| sort -rn` | the 11-row table above |
| Full suite (must stay green) | `python -m pytest -q` | `68 passed` (`72` if plan 022 landed first — see "If plan 022 has already landed" below) |
| Test files on disk | `ls tests/test_*.py \| wc -l` | `11` (`12` if plan 022 landed first) |
| CI Python version | `grep -n "python-version" .github/workflows/test.yml` | `21:          python-version: "3.13"` |
| Declared floor | `grep -n "requires-python" pyproject.toml` | `9:requires-python = ">=3.11"` |
| No stale 3.11 CI claim remains | `grep -n "CI pins\|Python 3.11, ubuntu" docs/codebase/STACK.md` | no matches |
| No stale plan-011 TODO remains | `grep -n "plan 011, TODO" docs/codebase/TESTING.md` | no matches |

If a repo-local `.venv` exists, use `.venv/bin/python -m pytest ...` instead of
`python -m pytest ...`.

## Scope

**In scope** (the only files you should modify):
- `docs/codebase/STACK.md` (lines 5, 6, 49, 53 only)
- `docs/codebase/TESTING.md` (the `## Organization` tree, the `## What Is Covered`
  list, and lines 58 and 61 of `## Gaps / Not Covered`)
- `plans/README.md` (status row update only)

**Out of scope** (do NOT touch, even though they look related):
- Any file under `src/`, `tests/`, `.github/`, or `pyproject.toml` — this plan
  changes documentation to match the code, never the reverse. If a doc claim looks
  wrong *about the code* rather than *stale*, STOP and report.
- `docs/codebase/ARCHITECTURE.md`, `CONCERNS.md`, `CONVENTIONS.md`,
  `INTEGRATIONS.md`, `STRUCTURE.md` — their test counts (68) and module lists were
  spot-checked and are **correct**; leave them alone.
- `STACK.md`'s "Linting / Formatting" section (line 42) and the `[tool.ruff]` half
  of line 53 — accurate today. **Plan 018** (CI Ruff gate) owns updating those when
  it lands; touching them here would collide.
- `CLAUDE.md` — accurate; not part of this plan.
- The `file:line` anchors elsewhere in `docs/codebase/` that still use bare module
  names (`config.py:7`, `email_notifier.py:1-2`) rather than
  `src/bigdataball/config.py:7`. That's a repo-wide stylistic sweep, deliberately
  deferred — see Maintenance notes. Only the four `STACK.md` lines named above
  change.

## Git workflow

- Branch: `advisor/023-refresh-stale-codebase-docs` (or the repo's branch-naming
  convention if one is evident from `git log --oneline`).
- Commit message style: match `git log` — imperative, no prefix, e.g.
  "Correct stale Python-version and test-inventory facts in codebase docs".
- Do NOT push or open a PR unless the operator instructed it.

### Note if `.pre-commit-config.yaml` exists

If plans 018/021 have landed by the time you run this, a Ruff format hook may be
configured. Ruff ≥ 0.16 formats Python code blocks inside Markdown by default, and
the plan-018 gate is scoped to `src tests` precisely so `docs/` is not touched. Do
not run `ruff format` over `docs/` and do not let a hook reformat these files. If a
hook rewrites them, STOP and report.

## If plan 022 has already landed (read before Step 0)

Plan 022 adds `tests/test_run_db_patch.py` (4 tests), taking the suite from 68 to
72. That is the **one** anticipated difference between this plan's tables and the
live repo, and it is expected — not drift. If `ls tests/test_run_db_patch.py`
succeeds, apply these three adjustments and otherwise follow the plan unchanged:

1. **Step 3 tree** — add a 12th row, positioned by its count (4 tests, so between
   `test_seasons.py`/`test_patch_fantasy_id_types.py` at 3 and
   `test_create_summary_tables.py` at 5):
   `├── test_run_db_patch.py               # 4  — retroactive name patch + connection cleanup`
   The tree's counts then sum to **72**, not 68.
2. **Step 4** — add an eleventh coverage bullet after the
   `test_create_summary_tables.py` one, describing the 4 tests you can read in the
   file (do not copy this description blindly — open the file):
   `- **`test_run_db_patch.py`** (4): happy-path rename + commit, missing tables skipped, an unexpected `OperationalError` still closes the connection, and an aborted run commits nothing (plan 022).`
3. **Step 5, line 58** — also drop `run_db_patch.py` from the "No tests" list,
   leaving `verify_db_patch.py` there on its own.

Everywhere this plan says `68 passed`, read `72 passed`; everywhere it says the
tree sums to `68`, read `72`; everywhere it says `10` coverage bullets, read `11`.
Nothing else changes. If `tests/test_run_db_patch.py` does **not** exist, ignore
this section entirely.

## Steps

### Step 0: Re-verify every corrected value before editing

Run all six verification commands in the "Commands you will need" table. Every one
must produce the stated expected output.

**Verify**: all six commands match. If the per-file counts differ from the table in
"Current state" **for any reason other than plan 022's `test_run_db_patch.py`**, the
suite changed since this plan was written — STOP and report the actual counts rather
than writing the ones in this plan. Write the counts you measured here, never the
ones transcribed from this file.

### Step 1: Fix the two `## Language & Runtime` bullets in `STACK.md`

Replace **line 5** with:

```
- **Language:** Python. Local development uses **3.13.3** (the git-ignored `venv/`); CI pins **3.13** (`.github/workflows/test.yml:21`). `pyproject.toml` declares `requires-python = ">=3.11"` (`pyproject.toml:9`), so 3.11 is the enforced floor — code must remain compatible across 3.11–3.13.
```

Replace **line 6** with the same text but the CI anchor corrected from `:10` to
`:13`:

```
- **Platform:** Primary development/runtime environment is Windows 11 (paths like `G:\My Drive\...` are hardcoded; see `config.py:7`). CI runs on `ubuntu-latest` (`.github/workflows/test.yml:13`).
```

(Everything else on line 6 is unchanged — do not touch the `config.py:7` anchor.)

**Verify**:
- `grep -n "CI pins" docs/codebase/STACK.md` → one match, containing `**3.13**`
  and `test.yml:21`
- `grep -c "requires-python" docs/codebase/STACK.md` → at least `1`
- `grep -n "test.yml:10" docs/codebase/STACK.md` → no matches

### Step 2: Fix the two `## Evidence` bullets in `STACK.md`

Replace **line 49** with:

```
- `.github/workflows/test.yml` (Python 3.13, ubuntu-latest, `pip install -r requirements.txt -r requirements-dev.txt` + `pip install -e .` + pytest)
```

Replace **line 53** with:

```
- `pyproject.toml` (setuptools src-layout manifest; `requires-python = ">=3.11"`, no `[tool.ruff]` section, no runtime deps declared)
```

**Verify**: `grep -n "Python 3.11" docs/codebase/STACK.md` → no matches.

### Step 3: Rebuild the `## Organization` tree in `TESTING.md`

Replace lines 25–33 (the `test_*.py` rows) so all **11** modules appear, ordered by
descending test count to match the existing convention, with counts that sum to 68.
Keep the `├──`/`└──` characters correct (last row uses `└──`) and keep the column
alignment of the `#` comments:

```
├── test_absence_ingestion.py         # 11 — DNP-DND-NWT sheet → player_absences
├── test_daily_fantasy_log_upload.py  # 10 — fantasy-log ingestion (inline loop)
├── test_check_ingest_duplicates.py   # 10 — dedup detection/removal
├── test_seed_map_teams.py            # 9  — map_teams seeding
├── test_dk_matching.py               # 8  — DraftKings load + fuzzy match helper
├── test_daily_player_upload.py       # 6  — box-score ingestion behavior
├── test_create_summary_tables.py     # 5  — fantasy_averages + view rebuild
├── test_seasons.py                   # 3  — season-filter constants/SQL
├── test_patch_fantasy_id_types.py    # 3  — one-time ID-affinity migration
├── test_paths.py                     # 2  — resolve_base_data_path precedence
└── test_orchestrator_warnings.py     # 1  — unmatched-players worklist warning
```

Leave lines 21–24 (`tests/`, `__init__.py`, `conftest.py`, `helpers.py`) exactly as
they are.

**Verify**: the `#` counts in the tree sum to `68`, and
`grep -c "test_create_summary_tables.py\|test_patch_fantasy_id_types.py" docs/codebase/TESTING.md`
→ at least `2`.

### Step 4: Fix and extend the `## What Is Covered` list in `TESTING.md`

**4a.** Change the count on line 39 from `(6)` to `(10)` and extend its description
to cover the four plan-014 tests. Replacement for line 39:

```
- **`test_daily_fantasy_log_upload.py`** (10): single-file fantasy-log load + player learning, name standardization, `DRAFTKINGS1` column drop/rename, ISO date handling (plan 010); cross-file dedup in one run (plan 003) and the UNIQUE-index backstop (plan 012); and INTEGER `PLAYER_ID` storage, no-duplicate re-runs after the int cast, fractional-ID rejection, and the missing-ID drop being counted and surfaced in the email (plan 014). Uses a module-scoped `autouse` fixture that no-ops `email_notifier.send_email_alert` so `main()`-driving tests don't attempt a real SMTP send.
```

**4b.** Add two new bullets for the missing modules. Insert them so the list keeps
its existing rough descending-count order — put the `test_create_summary_tables.py`
bullet immediately **after** the `test_dk_matching.py` bullet (line 42), and the
`test_patch_fantasy_id_types.py` bullet immediately **after** the
`test_seed_map_teams.py` bullet (line 43):

```
- **`test_create_summary_tables.py`** (5): the missing-tables guard returns `False`; basic aggregation builds `fantasy_averages` (GP/FPPG/SEASON/TEAM/canonical PLAYER); Regular-vs-Playoffs `SEASON_TYPE` + `SEASON_KEY` formatting; the L30FPPM 30-day window vs. all-games FPPM; and `run_summary_pipeline` view creation (plan 011).
```

```
- **`test_patch_fantasy_id_types.py`** (3): the one-time `fantasy_logs` ID migration flips column affinity to INTEGER while preserving data and re-creating the UNIQUE index, is idempotent (second run skips the backup), and rejects fractional IDs (plan 014).
```

**Verify**: `grep -c '^- \*\*.test_' docs/codebase/TESTING.md` → `10`.

Ten bullets, not eleven, because `test_seasons.py` and `test_paths.py` share one
combined bullet (line 44) — leave that combined bullet exactly as-is. Confirm by
eye that every one of the 11 files in the Step 3 tree is named somewhere in
`## What Is Covered`.

### Step 5: Fix the two stale claims in `## Gaps / Not Covered` in `TESTING.md`

Replace **line 58** with (drops `create_summary_tables.py`, which is now covered):

```
- **No tests** for the view-building bodies of the three `export_*` scripts (their DK-matching helper *is* tested via `test_dk_matching.py`), `drive_ingestion.py`/`auth_manager.py` (Google Drive), `email_notifier.py`, or `run_db_patch.py`/`verify_db_patch.py`.
```

Replace **line 61** with (repoints from the DONE plan 011 to the open plan 019):

```
- **Broadening coverage to the export view-builders stays a near-term goal** (plan 019). `create_summary_tables.py` is now covered (plan 011, DONE). The `player_upload` env-seam fixture pattern (fresh import under `BIGDATABALL_DATA_DIR`, dispose engine on teardown) is the template to extend; the export scripts additionally need a seeded `map_teams` table (now easy via `seed_map_teams.py`) and the player-average views in place.
```

Leave lines 57, 59, and 60 unchanged — all three are still accurate.

**Verify**:
- `grep -n "plan 011, TODO" docs/codebase/TESTING.md` → no matches
- `grep -n "plan 019" docs/codebase/TESTING.md` → one match

### Step 6: Confirm nothing else changed

**Verify**:
- `python -m pytest -q` → the same count as your Step 0 baseline (docs-only change;
  the suite must be untouched)
- `git status --porcelain` → exactly ` M docs/codebase/STACK.md`,
  ` M docs/codebase/TESTING.md`, and optionally ` M plans/README.md`. Nothing else.

## Test plan

No new tests. This plan changes Markdown only; correctness is verified by the
`grep` assertions in each step plus an unchanged suite result (`68 passed`, or
`72 passed` if plan 022 landed first).

The substantive check is that every number written into `TESTING.md` came from the
live `--collect-only` output in Step 0, not from this plan file. If Step 0's counts
disagreed with the table above, you should have stopped rather than transcribed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "Python 3.11" docs/codebase/STACK.md` returns `0`
- [ ] `grep -c "test.yml:10" docs/codebase/STACK.md` returns `0`
- [ ] `grep -c "test.yml:21" docs/codebase/STACK.md` returns `1`
- [ ] `grep -c "requires-python" docs/codebase/STACK.md` returns `2`
- [ ] `grep -c "plan 011, TODO" docs/codebase/TESTING.md` returns `0`
- [ ] `grep -c "test_create_summary_tables.py" docs/codebase/TESTING.md` returns `2`
      (one tree row, one coverage bullet)
- [ ] `grep -c "test_patch_fantasy_id_types.py" docs/codebase/TESTING.md` returns `2`
- [ ] Every `test_*.py` file that `ls tests/` reports has exactly one row in the
      `TESTING.md` `## Organization` tree, and the tree's `#` counts sum to the
      number `python -m pytest -q` reports (68, or 72 if plan 022 landed)
- [ ] `python -m pytest -q` passes with the same count as the Step 0 baseline
- [ ] `git diff --stat` lists only `docs/codebase/STACK.md`,
      `docs/codebase/TESTING.md`, and optionally `plans/README.md`
- [ ] `plans/README.md` status row updated (skip if a reviewer maintains the index)

## STOP conditions

Stop and report back (do not improvise) if:

- Step 0's per-file test counts do not match the table in "Current state" — the
  numbers this plan tells you to write would then be wrong.
- `.github/workflows/test.yml` no longer pins `3.13`, or `pyproject.toml` no longer
  declares `requires-python = ">=3.11"`.
- Any line in "Current state" does not match the live file verbatim.
- Fixing a doc claim seems to require changing code, config, or a test — it never
  does in this plan; that's a signal you found a *different* problem. Report it,
  don't fix it.
- Plans 018 or 021 have landed and `STACK.md`'s "Linting / Formatting" section now
  also looks stale. That section is plan 018's to update; report the overlap
  instead of editing it here.

## Maintenance notes

- **For the reviewer**: this is a pure-Markdown diff. Check each changed number
  against the repo rather than against the plan — the whole point is that the doc
  matches reality. `python -m pytest -q --collect-only | grep -c "::"` should equal
  the tree's sum.
- **Why this drifts**: `TESTING.md`'s per-file counts go stale every time a plan
  adds tests. Whoever lands a test-adding plan should update the tree row and the
  coverage bullet in the same PR. Plan 019 (export view-builder tests) and plan 022
  (`run_db_patch.py` tests) will both need exactly that — plan 022's maintenance
  note already flags it.
- **Deliberately deferred** (do not do it here): several `docs/codebase/` files
  still cite modules by bare filename (`config.py:7`, `email_notifier.py:1-2`,
  `check_ingest_duplicates.py:72-76`) rather than the post-plan-009 package path
  `src/bigdataball/…`. Those anchors still resolve unambiguously — there is exactly
  one file with each name — so it's a cosmetic sweep across five files, best done
  in one dedicated pass rather than smuggled into this correctness fix.
- **Interacts with plan 018**: when the CI Ruff gate lands, `STACK.md` line 42
  ("Ruff … via the VS Code Ruff extension … CI does **not** run Ruff") and the
  `[tool.ruff]` clause on line 53 both become false. Plan 018 already instructs its
  executor to update that section; this plan deliberately leaves it alone so the
  two don't conflict.
