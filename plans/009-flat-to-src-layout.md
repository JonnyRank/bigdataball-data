# Plan 009: Convert the flat module layout to a `src/bigdataball/` package

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f142763..HEAD -- '*.py' pytest.ini .github/workflows/test.yml`
> If any of the listed `.py` files, `pytest.ini`, or the workflow changed
> since this plan was written, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (but see "Maintenance notes" — landing this rebases the file paths of the still-open plans 010–012; 003–008 are already merged)
- **Category**: tech-debt
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/32
- **Planned at**: commit `c2f810f`, 2026-06-22 (refreshed for the merges of plans 006/007/008; prior bases `a852503` 2026-06-21 for plan 005's merge `#24`, `198d5b9` 2026-06-20, `8bf4ce0` 2026-06-18; original `a91aac1` 2026-06-17). **Major refresh (2026-06-22):** plans 006/007/008 merged three new runtime modules — `dk_matching.py` (plan 006, `import mappings`), `seasons.py` (plan 007, no internal imports), and `seed_map_teams.py` (plan 008, a **lazy** `import paths` inside `main()`). Consequences for this plan, all handled below: (1) there are now **18** runtime modules to move, not 15; (2) the three export scripts no longer `import mappings` — they now `import dk_matching` and `import seasons` (Step 2 entries corrected); (3) `seed_map_teams.py` has a **second** `__file__`-based `Data/` fallback (line 166) inside its `except` branch, so Step 3 now deepens **two** files, not one; (4) plans 006/007/008 also added three test files (`test_dk_matching` 8, `test_seasons` 3, `test_seed_map_teams` 9) that `import` their module **at top level** and must be converted to `from bigdataball import <module>` (Step 6) → total test count is now **38**, not 18.
- **Refresh (2026-07-19, reconcile @ `967d88a`)**: plan 013 (merged `#38`) added **three** new
  runtime modules — `absence_ingestion.py` (`import mappings`, line 10),
  `backfill_player_absences.py` (`import absence_ingestion` + `import paths`, lines 18–19), and
  `patch_absence_column_names.py` (`import paths`, line 19) — plus a top-level
  `import absence_ingestion` in `daily_player_upload.py` (line 13). There are now **21** modules
  to move. Neither new module adds a `__file__`-based path fallback (the Step 3 inventory of
  exactly two files still holds), and both new scripts are import-safe (engines are created
  inside `main()`), so all three join the Step 7 smoke list. Plan 013 also added
  `tests/test_absence_ingestion.py` (9 tests, imports only from `tests.helpers` — **no changes
  needed** in Step 6) → total test count is now **47**, not 38. `tests/conftest.py` gained an
  email-marking wrapper inside `fantasy_upload` (fixture bodies shifted a few lines;
  `_FANTASY_DEPS` still lists the same 8 bare module names and does **not** include
  `absence_ingestion` — no extra entries needed, just the `bigdataball.` prefixing already
  specified). All step-level counts and lists below have been updated in place to the
  21-module / 47-test state.
- **Refresh (2026-07-22, reconcile @ `f142763`)**: plan 012 (merged `#43`) added **one** new
  runtime module — `create_log_indexes.py` (`import paths` at **top level**, line 47). There are
  now **22** modules to move. It carries **no** `__file__`-based path fallback (it delegates
  path resolution to `paths`), so the Step 3 inventory of exactly two files (`paths.py`,
  `seed_map_teams.py`) still holds; its top-level `import paths` becomes `from . import paths`
  in Step 2, and it is import-safe (all DB work is inside `main()` behind `if __name__ ==
  "__main__"`), so it joins the Step 7 smoke list. Plan 012 added **no** new test files but grew
  three existing ones — `test_absence_ingestion.py` (9→**11**), `test_daily_player_upload.py`
  (4→**6**), and `test_daily_fantasy_log_upload.py` (1→**2**) — all using fixtures/`tests.helpers`
  with **no top-level module imports to convert** in Step 6. Total test count is now **52**, not
  47. All step-level counts and lists below have been updated in place to the 22-module /
  52-test state.
- **Earlier refresh (plan 005, `a852503`)**: plan 005 added `paths.py` and consolidated every per-script `PROJECT_ROOT`/`Data/`-fallback into `paths.resolve_base_data_path()`; nine modules now `import paths` and must become `from . import paths` (Step 2); the primary `__file__`-based path fix (Step 3) lives in `paths.py`; plan 005 added `tests/test_paths.py` (2 tests).

## Why this matters

The repo is a flat collection of 22 top-level `.py` modules that import each
other by bare name (`import mappings`, `from auth_manager import ...`). A flat
layout makes the importable code indistinguishable from scripts, config, and
tests at the repo root, lets tests accidentally import from the working
directory instead of an installed package, and has no single packaging
manifest. Moving to the standard **src layout** (`src/bigdataball/`) with a
`pyproject.toml` gives the project one installable package, a clean import
namespace, and a clean foundation for further work (plans 005–008, all of which
are already DONE and merged, were built on the flat layout; this move tidies up
after them). This plan is deliberately the **minimum** mechanical move: create the
folder, move the files, fix the imports and the two `__file__`-based paths that
break when files move deeper, add `pyproject.toml`, and update the test/CI wiring.
No logic changes, no API changes, no new behavior.

## Current state

All 22 runtime modules live at the repo root. Each is an importable module; most
are also runnable directly (`if __name__ == "__main__"`). The cross-module import
graph (verified at commit `f142763`; line numbers are where the import appears):

```
config.py                            (no internal imports)
mappings.py                          (no internal imports)
seasons.py                           (no internal imports — pure constants, plan 007)
paths.py                             (no internal imports — pure stdlib, plan 005)
dk_matching.py:3                     import mappings                       (plan 006)
absence_ingestion.py:10              import mappings                       (plan 013)
backfill_player_absences.py:18-19    import absence_ingestion ; import paths   (plan 013)
patch_absence_column_names.py:19     import paths                          (plan 013)
auth_manager.py:5                    import config
email_notifier.py:3                  import config
check_ingest_duplicates.py:77        import paths
create_log_indexes.py:47             import paths                          (plan 012)
create_summary_tables.py:7           import paths
daily_player_upload.py:13-15         import absence_ingestion ; import mappings ; import paths
run_db_patch.py:3-4                  import mappings ; import paths
verify_db_patch.py:3-4               import mappings ; import paths
export_slate_averages_csv.py:15-17   import dk_matching ; import paths ; import seasons
export_slate_averages_vw.py:11-13    import dk_matching ; import paths ; import seasons
export_playoffs_slate_averages_vw.py:11-13  import dk_matching ; import paths ; import seasons
seed_map_teams.py:155                import paths   (LAZY — inside main(), indented, see below)
drive_ingestion.py:5                 from auth_manager import authenticate_google_drive
drive_ingestion.py:6                 import config
daily_fantasy_log_upload.py:12-20    import create_summary_tables
                                     import export_slate_averages_vw
                                     import export_playoffs_slate_averages_vw
                                     import export_slate_averages_csv
                                     import daily_player_upload
                                     import drive_ingestion
                                     import email_notifier
                                     import mappings
                                     import paths
```

Note the three export scripts **no longer** `import mappings` (plan 006 moved the
fuzzy-match logic into `dk_matching`, which is what now wraps `mappings`). They
import `dk_matching` and `seasons` instead. `config.py`, `mappings.py`,
`seasons.py`, and `paths.py` have **no** internal imports.

`seed_map_teams.py` is special: its only internal import is a **lazy**
`import paths` inside `main()` (line 155), guarded by a `try/except` (see the
gotcha note below). It is indented two levels (inside `try:` inside `main()`).

**The critical gotcha — `__file__`-based path resolution (now TWO files).** As of
plan 005 the primary `Data/` fallback lives in `paths.py`. All data-touching
scripts call `paths.resolve_base_data_path()` rather than computing their own
`PROJECT_ROOT`. The relevant code is `paths.py:17-18`:

```python
project_root = os.path.dirname(os.path.abspath(__file__))
return os.path.join(project_root, "Data")
```

Today `paths.py` sits at the repo root, so `project_root` **is** the repo root.
After the move to `src/bigdataball/paths.py`, `dirname(abspath(__file__))`
becomes `<repo>/src/bigdataball`, so the local fallback would resolve to
`<repo>/src/bigdataball/Data` instead of `<repo>/Data`. **This must be fixed** in
`paths.py` by walking up two extra directory levels (Step 3).

**`seed_map_teams.py` carries a SECOND copy** of this fallback inside its
`except` branch (`seed_map_teams.py:166`):

```python
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")
```

This branch only runs if the lazy `import paths` on line 155 fails. After the
move, that line becomes `from . import paths` (Step 2), so the `try` succeeds and
the `except` is dead in practice — but the dead line still resolves `__file__`
relative to `src/bigdataball/`, so for correctness Step 3 deepens **both** files.
Verify the inventory with
`grep -rn "os.path.dirname(os.path.abspath(__file__))" *.py` → exactly **two**
matches: `paths.py:17` and `seed_map_teams.py:166`. If you find a third, STOP
(the import graph differs from what this plan assumed).

`config.py` hardcodes `BASE_DOWNLOAD_DIR = r"G:\My Drive\..."` with no
`__file__`/`Data/` logic, and `drive_ingestion.py` derives its paths from
`config`, so **neither needs the path fix** — only the import fix.
`auth_manager.py` and `email_notifier.py` have no path logic either.

**Test harness** (current, as of 8bf4ce0):
- `pytest.ini`: `pythonpath = .` and `testpaths = tests`.
- `tests/conftest.py` now has **two** fixtures with module-name references:
  - `fantasy_upload` fixture (added in commit `f6d787f`): has a `_FANTASY_DEPS`
    list of bare module names plus an `importlib.import_module("daily_fantasy_log_upload")`
    call. All entries in `_FANTASY_DEPS` and the `import_module` call need the
    `bigdataball.` prefix. A `_STUB_MODULES` dict stubs `"drive_ingestion"` by key —
    after the move, the stub key must become `"bigdataball.drive_ingestion"` because
    relative imports inside the package resolve to the package namespace.
  - `player_upload` fixture: `sys.modules.pop("daily_player_upload", None)` (two
    occurrences) and `importlib.import_module("daily_player_upload")` — these also
    need the `bigdataball.` prefix.
- `tests/test_check_ingest_duplicates.py`: references `"check_ingest_duplicates"` via
  `sys.modules.pop` and `import_module` — needs `bigdataball.` prefix.
- `tests/test_daily_fantasy_log_upload.py` (added in `f6d787f`): uses the
  `fantasy_upload` fixture via pytest injection — **no direct `import_module` calls,
  no changes needed**.
- `tests/test_daily_player_upload.py`: `from tests.helpers import ...` (a `tests.`
  import — stays valid, see Step 6). No `import_module` calls.
- `tests/test_orchestrator_warnings.py` (added in plan 004's merge `f236ef5`): uses the
  `fantasy_upload` fixture via pytest injection and references submodules as attributes of
  the loaded module (`mod.daily_player_upload`, etc.) — **no direct `import_module` calls,
  no bare module-name strings, no changes needed**.
- `tests/test_paths.py` (added by plan 005): two tests that call `import paths`
  **inside** the test functions and reference `paths.resolve_base_data_path()` /
  `paths.__file__`. After the move, two edits are needed (details in Step 6):
  (1) replace both local `import paths` lines with `from bigdataball import paths`;
  (2) **deepen the `expected` assertion** in `test_fallback_to_local_data` to go up
  three levels, matching Step 3's change to `paths.py`. Currently it computes
  `expected = os.path.join(os.path.dirname(os.path.abspath(paths.__file__)), "Data")`
  (single `dirname`). After Step 3, `resolve_base_data_path()` returns the **repo
  root** `Data/` (triple `dirname`), so the test's single-`dirname` expected would
  resolve to `src/bigdataball/Data` and the assertion would fail. The expected must
  use the same triple-`dirname` so both sides point at the repo-root `Data/`.
- `tests/test_dk_matching.py` (plan 006, 8 tests), `tests/test_seasons.py` (plan 007,
  3 tests), and `tests/test_seed_map_teams.py` (plan 008, 9 tests) each `import` their
  module **at module top level** (`import dk_matching`, `import seasons`,
  `import seed_map_teams` respectively — line 1, 1, and 5). Under today's
  `pythonpath = .` these resolve to the root modules; after Step 5 sets
  `pythonpath = src`, a bare `import dk_matching` fails (the module now lives at
  `bigdataball.dk_matching`). Each of these three top-level imports must become
  `from bigdataball import <module>` (Step 6). The later references in those tests
  (`dk_matching.<x>`, `seasons.<x>`, `seed_map_teams.<x>`) stay unchanged.
- `tests/test_absence_ingestion.py` (added by plan 013, 9 tests): imports only from
  `tests.helpers` and uses the `player_upload` fixture via injection — **no direct
  `import_module` calls, no bare module-name strings, no changes needed**.
- `tests/helpers.py`, `tests/__init__.py` need no changes.
- **Total test count is 52** (11 absence_ingestion + 10 check_ingest + 6 player_upload +
  2 fantasy_upload + 1 orchestrator_warnings + 2 paths + 8 dk_matching + 3 seasons +
  9 seed_map_teams).
  Plan 009 adds no tests and removes none; the executor should see 52 pass after the move.

**CI**: `.github/workflows/test.yml` installs
`pip install -r requirements.txt -r requirements-dev.txt` then runs
`python -m pytest -q`.

**Repo conventions to match**: imports at the top of each file, standard-library
imports grouped first (see `daily_player_upload.py:9-13`). Use **package-relative
imports** (`from . import mappings`) so the later module-reference names in the
code (`mappings.PLAYER_NAME_MAP`, `create_summary_tables.main()`, etc.) stay
unchanged — only the import line changes, never the call sites.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run tests | `python -m pytest -q` | all tests pass, exit 0 |
| Editable install | `pip install -e .` | exit 0, `Successfully installed bigdataball-...` |
| Import smoke test | (see Step 7) | prints `ALL IMPORTS OK`, exit 0 |
| List package files | `ls src/bigdataball/` | the 22 modules + `__init__.py` |
| Confirm no stray root modules | `ls *.py` | `No such file or directory` (or only non-package files if any remain) |

## Scope

**In scope** (the only files you should create, move, or modify):

- Move (with `git mv`) these 22 files from repo root into `src/bigdataball/`:
  `absence_ingestion.py`, `auth_manager.py`, `backfill_player_absences.py`,
  `check_ingest_duplicates.py`, `config.py`, `create_log_indexes.py`,
  `create_summary_tables.py`, `daily_fantasy_log_upload.py`,
  `daily_player_upload.py`, `dk_matching.py`, `drive_ingestion.py`,
  `email_notifier.py`, `export_playoffs_slate_averages_vw.py`,
  `export_slate_averages_csv.py`, `export_slate_averages_vw.py`, `mappings.py`,
  `patch_absence_column_names.py`, `paths.py`, `run_db_patch.py`, `seasons.py`,
  `seed_map_teams.py`, `verify_db_patch.py`
- Create `src/bigdataball/__init__.py` (empty)
- Create `pyproject.toml` (repo root)
- Edit `pytest.ini`
- Edit `.github/workflows/test.yml`
- Edit `tests/conftest.py`, `tests/test_check_ingest_duplicates.py`,
  `tests/test_paths.py`, `tests/test_dk_matching.py`, `tests/test_seasons.py`,
  `tests/test_seed_map_teams.py`
- Edit the import lines and `PROJECT_ROOT` lines inside the moved modules (per
  the tables above)
- Edit the documentation command blocks in `CLAUDE.md` and
  `.github/copilot-instructions.md` (Step 9 — command snippets only)
- Edit the in-code usage strings inside `src/bigdataball/check_ingest_duplicates.py`
  (Step 9 — the module-docstring `Usage` block and the "rebuild derived data next"
  print block; string/comment literals only, no logic)
- Update `plans/README.md` status row (final step)

**Out of scope** (do NOT touch, even though they look related):

- Any change to function bodies, SQL, logic, or behavior beyond the import lines
  and the `PROJECT_ROOT` expression. This is a move, not a refactor.
- `requirements.txt` / `requirements-dev.txt` — dependency declarations stay
  there for now; do **not** move them into `pyproject.toml` (deferred follow-up).
- Adding `[project.scripts]` console entry points — deliberately deferred:
  `daily_player_upload.main()` returns a tuple, which would become a non-zero
  exit code under a console-script wrapper. Use `python -m bigdataball.<module>`
  instead. Do not add console scripts in this plan.
- The other plans in `plans/` (003–008) — do not execute or edit them; just
  note in your report that their file paths now live under `src/bigdataball/`.
- `tests/helpers.py`, `tests/__init__.py`, `config.py`'s path logic.
- Prose/architecture sections of `CLAUDE.md` beyond the runnable command blocks.

## Git workflow

- Create a new branch for this work (e.g. `claude/src-layout`) and stay on it.
- Use `git mv` (not plain `mv`) so history follows the files.
- Commit in logical units (e.g. one commit for the move + imports, one for
  packaging/test wiring, one for docs). Match the repo's plain, imperative
  commit-message style (see `git log --oneline -10`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create the package directory and move the modules

Create `src/bigdataball/` and `git mv` all 22 in-scope modules into it. Then
create an empty `src/bigdataball/__init__.py`.

```bash
mkdir -p src/bigdataball
git mv absence_ingestion.py auth_manager.py backfill_player_absences.py \
       check_ingest_duplicates.py config.py create_log_indexes.py \
       create_summary_tables.py daily_fantasy_log_upload.py daily_player_upload.py \
       dk_matching.py drive_ingestion.py email_notifier.py \
       export_playoffs_slate_averages_vw.py export_slate_averages_csv.py \
       export_slate_averages_vw.py mappings.py patch_absence_column_names.py \
       paths.py run_db_patch.py \
       seasons.py seed_map_teams.py verify_db_patch.py src/bigdataball/
touch src/bigdataball/__init__.py
```

**Verify**: `ls src/bigdataball/` → lists the 22 modules plus `__init__.py`.
`ls *.py` at repo root → `No such file or directory` (no module files left at
root). `python -m pytest -q` will FAIL here (imports not yet fixed) — that is
expected; do not try to fix tests yet.

### Step 2: Convert cross-module imports to package-relative imports

Edit the moved files so every internal import becomes a relative import. The
module-reference name used elsewhere in each file is unchanged — only the
`import` line changes. Make exactly these replacements:

- `src/bigdataball/dk_matching.py`: `import mappings` → `from . import mappings`
- `src/bigdataball/absence_ingestion.py`: `import mappings` → `from . import mappings`
- `src/bigdataball/backfill_player_absences.py`: `import absence_ingestion` → `from . import absence_ingestion`; `import paths` → `from . import paths`
- `src/bigdataball/patch_absence_column_names.py`: `import paths` → `from . import paths`
- `src/bigdataball/daily_player_upload.py`: `import absence_ingestion` → `from . import absence_ingestion`; `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/email_notifier.py`: `import config` → `from . import config`
- `src/bigdataball/auth_manager.py`: `import config` → `from . import config`
- `src/bigdataball/run_db_patch.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/export_slate_averages_csv.py`: `import dk_matching` → `from . import dk_matching`; `import paths` → `from . import paths`; `import seasons` → `from . import seasons` (these scripts no longer import `mappings`)
- `src/bigdataball/export_slate_averages_vw.py`: `import dk_matching` → `from . import dk_matching`; `import paths` → `from . import paths`; `import seasons` → `from . import seasons`
- `src/bigdataball/export_playoffs_slate_averages_vw.py`: `import dk_matching` → `from . import dk_matching`; `import paths` → `from . import paths`; `import seasons` → `from . import seasons`
- `src/bigdataball/verify_db_patch.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/check_ingest_duplicates.py`: `import paths` → `from . import paths`
- `src/bigdataball/create_log_indexes.py`: `import paths` → `from . import paths` (top-level, line 47)
- `src/bigdataball/create_summary_tables.py`: `import paths` → `from . import paths`
- `src/bigdataball/seed_map_teams.py`: the **lazy** `import paths` inside `main()` (indented under `try:`, line 155) → `from . import paths`. Keep the same indentation; change only that line. (`seasons.py` has no internal imports — nothing to convert there.)
- `src/bigdataball/drive_ingestion.py`:
  - `from auth_manager import authenticate_google_drive` → `from .auth_manager import authenticate_google_drive`
  - `import config` → `from . import config`
- `src/bigdataball/daily_fantasy_log_upload.py`: replace the nine-line import
  block (currently lines 12–20)

  ```python
  import create_summary_tables
  import export_slate_averages_vw
  import export_playoffs_slate_averages_vw
  import export_slate_averages_csv
  import daily_player_upload
  import drive_ingestion
  import email_notifier
  import mappings
  import paths
  ```

  with:

  ```python
  from . import create_summary_tables
  from . import export_slate_averages_vw
  from . import export_playoffs_slate_averages_vw
  from . import export_slate_averages_csv
  from . import daily_player_upload
  from . import drive_ingestion
  from . import email_notifier
  from . import mappings
  from . import paths
  ```

**Verify**:
- `grep -rn -E "^import (mappings|paths|config|seasons|dk_matching|absence_ingestion|create_summary_tables|export_[a-z_]+|daily_player_upload|drive_ingestion|email_notifier)$|^from (auth_manager|config|mappings) import" src/bigdataball/` → **no matches** (all top-level internal imports are now relative). The `export_[a-z_]+` branch matches all three export modules (`export_slate_averages_vw`, `export_playoffs_slate_averages_vw`, `export_slate_averages_csv`), not just a bare `export_`.
- `grep -rn "^[[:space:]]\+import paths$" src/bigdataball/` → **no matches** (the indented lazy `import paths` in `seed_map_teams.py` is now `from . import paths`).

> **Expected behavior after this step — NOT a bug to "fix".** Once the internal
> imports are relative, running a module by its file path
> (`python src/bigdataball/daily_player_upload.py`) will raise
> `ImportError: attempted relative import with no known parent package`. This is
> correct and intended. From here on, every module must be run as
> `python -m bigdataball.<module>` (or exercised via the test suite). Do **not**
> revert to bare/absolute imports to make direct file execution work — that
> defeats the package layout. Step 9 updates the docs to the `-m` form.

### Step 3: Fix the `__file__`-based project-root resolution (the critical gotcha)

**Two files** carry an `__file__`-based `Data/` fallback: `paths.py` (the live one)
and `seed_map_teams.py` (a dead-after-Step-2 fallback inside its `except`). Deepen
**both** so neither resolves to `src/bigdataball/Data` after the move.

**3a — `src/bigdataball/paths.py`** (the live fallback, currently `paths.py:17-18`):

```python
project_root = os.path.dirname(os.path.abspath(__file__))
return os.path.join(project_root, "Data")
```

After the move, `dirname(abspath(__file__))` resolves to `<repo>/src/bigdataball`
instead of the repo root, so the fallback would point at
`<repo>/src/bigdataball/Data`. Replace those two lines with a version that walks
up two more levels back to the repo root, and add a clarifying comment:

```python
# Repo root: this module now lives at <repo>/src/bigdataball/paths.py,
# so go up three levels to reach <repo> (keeps the local Data/ fallback correct).
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
return os.path.join(project_root, "Data")
```

**3b — `src/bigdataball/seed_map_teams.py`** (the dead `except`-branch fallback,
currently `seed_map_teams.py:166`):

```python
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")
```

Deepen it the same way (this line is indented inside `except Exception:` —
preserve its indentation; change only the expression):

```python
base = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Data",
)
```

Edit **only** these two files. Do not add the fix anywhere else — no other module
computes a project root from `__file__`.

**Verify**:
- `grep -rn "os.path.dirname(os.path.abspath(__file__))" src/bigdataball/` → matches **only** `paths.py` and `seed_map_teams.py`, each now the inner expression of a triple-dirname replacement. The next grep is authoritative.
- `grep -rln "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))" src/bigdataball/` → lists exactly **two** files: `src/bigdataball/paths.py` and `src/bigdataball/seed_map_teams.py`.

### Step 4: Create `pyproject.toml`

Create `pyproject.toml` at the repo root with a minimal setuptools src-layout
configuration. Do **not** declare runtime dependencies here (they stay in
`requirements.txt` for this pass).

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

**Verify**: `pip install -e .` → exit 0, ending with
`Successfully installed bigdataball-0.1.0`. Then
`python -c "import bigdataball; print('pkg ok')"` → prints `pkg ok`.

### Step 5: Point pytest at `src`

Edit `pytest.ini`. Change the one line `pythonpath = .` to `pythonpath = src`.
Leave `testpaths = tests` unchanged. Final file:

```ini
[pytest]
pythonpath = src
testpaths = tests
```

(The `from tests.helpers import ...` import in the test suite continues to work
because pytest's default `prepend` import mode inserts the repo root — the first
parent without an `__init__.py` — onto `sys.path`; `tests/` has an
`__init__.py`, so the root is added and `tests` is importable.)

**Verify**: deferred to Step 8 (run the full suite after the test imports are
fixed in Step 6).

### Step 6: Update the test module references to the package namespace

Test artifacts reference modules by name in two ways: through `importlib`/`sys.modules`
(conftest, `test_check_ingest_duplicates`), and through a top-level `import <module>`
(`test_paths`, `test_dk_matching`, `test_seasons`, `test_seed_map_teams`). Both forms
break once the modules live under `bigdataball` — fix each as described below.

**`tests/conftest.py`** has two fixtures to update:

*`player_upload` fixture:*
- `sys.modules.pop("daily_player_upload", None)` → `sys.modules.pop("bigdataball.daily_player_upload", None)` (**two** occurrences — before `import_module` and in teardown)
- `importlib.import_module("daily_player_upload")` → `importlib.import_module("bigdataball.daily_player_upload")`

*`fantasy_upload` fixture:*
- In `_FANTASY_DEPS`, prefix every bare module name with `bigdataball.`:
  `"daily_fantasy_log_upload"` → `"bigdataball.daily_fantasy_log_upload"`, and the same for all other entries in that list.
- In `_STUB_MODULES`, rename the `"drive_ingestion"` key to `"bigdataball.drive_ingestion"`. (Relative imports inside the package resolve to `bigdataball.*` in `sys.modules`; a stub keyed on `"drive_ingestion"` would be missed.) The other entries in `_STUB_MODULES` — `"googleapiclient"`, `"google"`, `"google.oauth2"`, `"google_auth_oauthlib"`, etc. — are **external** packages that do not move into the `bigdataball` namespace; leave those keys unchanged.
- `importlib.import_module("daily_fantasy_log_upload")` → `importlib.import_module("bigdataball.daily_fantasy_log_upload")`

**`tests/test_check_ingest_duplicates.py`:**
- `sys.modules.pop("check_ingest_duplicates", None)` → `sys.modules.pop("bigdataball.check_ingest_duplicates", None)` (**both** occurrences)
- `importlib.import_module("check_ingest_duplicates")` → `importlib.import_module("bigdataball.check_ingest_duplicates")`

**`tests/test_paths.py`** (added by plan 005): two edits.

1. Each of its two test functions has a local `import paths` line. Change both to
   `from bigdataball import paths`.
2. In `test_fallback_to_local_data`, the `expected` line currently reads:

   ```python
   expected = os.path.join(os.path.dirname(os.path.abspath(paths.__file__)), "Data")
   ```

   This must be deepened to **three** `dirname` calls so it matches Step 3's change
   to `paths.resolve_base_data_path()` (which now returns the repo-root `Data/`).
   Without this, `result` (repo-root `Data/`) ≠ `expected` (`src/bigdataball/Data`)
   and the test fails. Replace it with:

   ```python
   expected = os.path.join(
       os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(paths.__file__)))),
       "Data",
   )
   ```

   (`test_env_override_wins` needs no change beyond the import — it asserts a literal
   override path.)

**`tests/test_dk_matching.py`, `tests/test_seasons.py`, `tests/test_seed_map_teams.py`**
(plans 006/007/008): each has a single top-level `import <module>` line that must
become a package import. Make exactly these changes (top-of-file, one line each):
- `tests/test_dk_matching.py:1`: `import dk_matching` → `from bigdataball import dk_matching`
- `tests/test_seasons.py:1`: `import seasons` → `from bigdataball import seasons`
- `tests/test_seed_map_teams.py:5`: `import seed_map_teams` → `from bigdataball import seed_map_teams`

The later references in those tests (`dk_matching.<x>`, `seasons.<x>`,
`seed_map_teams.<x>`) are unchanged — only the import line changes.

Do **not** change the `sys.argv = ["check_ingest_duplicates.py", ...]` lines —
those are the simulated program name (`argv[0]`) and have no import meaning.
Do **not** change `tests/test_daily_player_upload.py` or `tests/test_daily_fantasy_log_upload.py` — they use fixtures via injection and `from tests.helpers`, which remain valid.

**Verify**: `grep -rn "import_module(\"daily_player_upload\")\|import_module(\"daily_fantasy_log_upload\")\|import_module(\"check_ingest_duplicates\")" tests/` → **no matches** (all now carry the `bigdataball.` prefix).
Also: `grep -n '"drive_ingestion"' tests/conftest.py` → **no matches** (key renamed to `"bigdataball.drive_ingestion"`).
Also: `grep -n "^    import paths$" tests/test_paths.py` → **no matches** (both converted to `from bigdataball import paths`).
Also: `grep -rnE "^import (dk_matching|seasons|seed_map_teams)$" tests/` → **no matches** (all three converted to `from bigdataball import <module>`).

### Step 7: Import smoke test (all 22 modules)

With the package installed (Step 4) confirm every module imports cleanly under
the package namespace, including the relative imports. The command below is a
single pure-Python invocation (no shell-specific syntax — works on Windows,
macOS, and Linux): it creates its own throwaway data dir with
`tempfile.mkdtemp()` and points `BIGDATABALL_DATA_DIR` at it *before* importing,
so the two modules that `os.makedirs(...)` at import time don't write into the
repo:

```bash
python -c "import os, tempfile, importlib; os.environ['BIGDATABALL_DATA_DIR'] = tempfile.mkdtemp(); [importlib.import_module('bigdataball.'+m) for m in ['absence_ingestion','auth_manager','backfill_player_absences','check_ingest_duplicates','config','create_log_indexes','create_summary_tables','daily_fantasy_log_upload','daily_player_upload','dk_matching','drive_ingestion','email_notifier','export_playoffs_slate_averages_vw','export_slate_averages_csv','export_slate_averages_vw','mappings','patch_absence_column_names','paths','run_db_patch','seasons','seed_map_teams','verify_db_patch']]; print('ALL IMPORTS OK')"
```

**Verify**: prints `ALL IMPORTS OK`, exit 0. If any module raises
`ImportError`/`ModuleNotFoundError`, a relative import in Step 2 was missed —
fix it and re-run.

> **Note — `seed_map_teams`'s lazy import is NOT covered by this smoke test.**
> Importing `seed_map_teams` does not execute the `from . import paths` line,
> because it lives inside `main()` (Step 2), not at module top. So a bad
> conversion there would still pass this step. The real guard is
> `tests/test_seed_map_teams.py::test_main_derives_rows_from_fantasy_logs`
> (`tests/test_seed_map_teams.py:99`), which actually calls `seed_map_teams.main()`
> and therefore exercises the relative import — it runs in Step 8's `pytest`. Don't
> over-trust this smoke step for that one module.

### Step 8: Run the full test suite

**Verify**: `python -m pytest -q` → all **52 tests** pass, exit 0 (11
`test_absence_ingestion`, 10 `test_check_ingest_duplicates`, 6
`test_daily_player_upload`, 2 `test_daily_fantasy_log_upload`, 1
`test_orchestrator_warnings`, 2 `test_paths`, 8 `test_dk_matching`, 3
`test_seasons`, 9 `test_seed_map_teams`). This plan adds
no tests and removes none — if the count differs, something was moved or shadowed.
If any test errors with a `ModuleNotFoundError` for `bigdataball.*` or `tests.*`,
re-check Steps 5–6.

### Step 9: Update the runnable-command docs

The documented invocations (`python daily_fantasy_log_upload.py`, etc.) no longer
work — the modules are now under the package and must be run with `-m`. Update
**only the runnable command snippets** (the fenced `bash` blocks) in:

- `CLAUDE.md` — the `## Commands` section and the standalone-stage command list:
  rewrite each `python <module>.py [...]` as `python -m bigdataball.<module> [...]`
  (e.g. `python daily_fantasy_log_upload.py` → `python -m bigdataball.daily_fantasy_log_upload`;
  `python check_ingest_duplicates.py --remove` → `python -m bigdataball.check_ingest_duplicates --remove`).
  Leave `pip install -r requirements.txt`, the pytest commands, and all prose
  unchanged.
- `.github/copilot-instructions.md` — apply the same `python <module>.py` →
  `python -m bigdataball.<module>` substitution to any runnable command snippets
  (its command list now also includes
  `python backfill_player_absences.py <file...>` → `python -m bigdataball.backfill_player_absences <file...>`).

Also update the in-code "rebuild derived data next" message in
`src/bigdataball/check_ingest_duplicates.py` (the print block near lines
260–262) that lists `create_summary_tables.py, export_slate_averages_vw.py,
...` — change those `.py` names to the `python -m bigdataball.<module>` form so
the on-screen instruction stays accurate. This is a string-literal edit only; do
not change surrounding logic.

Also update the **module docstring usage block** at the top of
`src/bigdataball/check_ingest_duplicates.py` (the `Usage` section, currently lines
24–25, 29, and 66–69). These are the same kind of `python <module>.py` examples
and will be stale after the move. Rewrite each to the `-m` form, e.g.
`python check_ingest_duplicates.py --remove` → `python -m bigdataball.check_ingest_duplicates --remove`,
and `python create_summary_tables.py` → `python -m bigdataball.create_summary_tables`
(and the same for the three export modules listed there). String-literal/comment
edit only; do not change any logic.

**Verify**: `grep -rn "python [a-z_]*\.py" CLAUDE.md .github/copilot-instructions.md src/bigdataball/check_ingest_duplicates.py` → **no matches** (all converted to `python -m bigdataball.`; this includes the `check_ingest_duplicates.py` docstring usage block). `python -m pytest -q` still passes.

### Step 10: Wire the editable install into CI

Edit `.github/workflows/test.yml`. In the "Install dependencies" step, add an
editable install of the package after the requirements install, so CI validates
`pyproject.toml`:

```yaml
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
          pip install -e .
```

Leave the rest of the workflow unchanged.

**Verify**: `python -m pytest -q` still passes locally (the CI change itself is
validated when the workflow runs).

## Test plan

- **No new tests.** This is a structural move; the existing suite is the
  regression guard. The `player_upload` and `dedup_tool` fixtures already
  exercise that `bigdataball.daily_player_upload` and
  `bigdataball.check_ingest_duplicates` import and run end-to-end against a temp
  DB, which proves the relative imports and the `PROJECT_ROOT` depth fix work.
- The import smoke test in Step 7 covers the modules not directly imported by
  the test suite (orchestrator, exports, `seed_map_teams`, etc.).
- Structural pattern to follow if any fixture needs adjusting:
  `tests/conftest.py`'s existing `player_upload` fixture.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `ls src/bigdataball/__init__.py` exists; all 22 modules are under `src/bigdataball/`; `ls *.py` at repo root returns none.
- [ ] `pip install -e .` exits 0.
- [ ] `grep -rn -E "^import (mappings|paths|config|seasons|dk_matching|absence_ingestion|create_summary_tables|daily_player_upload|drive_ingestion|email_notifier|export_[a-z_]+)$|^from (auth_manager|config|mappings) import" src/bigdataball/` returns no matches, and `grep -rn "^[[:space:]]\+import paths$" src/bigdataball/` returns no matches (all internal imports relative, including the lazy one in `seed_map_teams.py` — same patterns as Step 2's verify).
- [ ] `grep -rln "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))" src/bigdataball/` lists exactly two files, `src/bigdataball/paths.py` and `src/bigdataball/seed_map_teams.py` (both `Data/`-fallback path-resolutions, deepened per Step 3).
- [ ] Step 7 import smoke test prints `ALL IMPORTS OK`.
- [ ] `python -m pytest -q` exits 0 with exactly 52 tests passing.
- [ ] `grep -rn "python [a-z_]*\.py" CLAUDE.md .github/copilot-instructions.md src/bigdataball/check_ingest_duplicates.py` returns no matches (docs **and** the `check_ingest_duplicates.py` docstring usage block all converted to `python -m bigdataball.`).
- [ ] CI workflow `.github/workflows/test.yml` runs `pip install -e .` before the tests (see Step 10).
- [ ] No files outside the in-scope list are modified (`git status`).
- [ ] `plans/README.md` status row for 009 updated to DONE.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any in-scope `.py` file, `pytest.ini`, or the workflow
  changed since commit `f142763`, and the "Current state" excerpts no longer
  match the live code.
- After Step 2/3, the import smoke test (Step 7) still raises an import error you
  cannot trace to a missed relative-import or a missed `PROJECT_ROOT` line — the
  import graph differs from what this plan assumed.
- `python -m pytest -q` reports a *different number of collected tests* than
  before the change (something was moved or shadowed that shouldn't have been).
- You find an internal import or `__file__`-based path expression **not** listed
  in the "Current state" tables (the codebase has a coupling this plan didn't
  account for).
- Fixing test imports appears to require touching `tests/helpers.py`,
  `tests/__init__.py`, or `tests/test_daily_player_upload.py` — that signals a
  deeper change than this plan intends.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- **This plan rebases the file paths of every still-open plan.** Plans 003–008 are
  already DONE and merged, so the only remaining ones this affects are **010–012**,
  which reference root-level files (e.g. `daily_fantasy_log_upload.py`,
  `create_summary_tables.py`, `daily_player_upload.py`). After 009 lands, those same
  files live at `src/bigdataball/...`. Their logic, line numbers, and excerpts are
  otherwise unaffected (009 only moves files and changes import lines + the
  `__file__`-fallback expressions). When executing 010–012 next, prepend
  `src/bigdataball/` to their in-scope paths. The `plans/README.md` dependency notes
  flag this.
- **Plan 005 is already DONE and merged (`#24`).** `paths.resolve_base_data_path()`
  already exists and is the single owner of the `Data/` fallback — Step 3 does not
  introduce it, it just *deepens* the `__file__`-relative resolution inside that
  existing function (three `dirname()` levels) so it still points at the repo root
  from the new `src/bigdataball/` depth. The second copy in `seed_map_teams.py`'s
  `except` branch is deepened the same way. There is no per-file `PROJECT_ROOT` to
  reconcile any more — 005 already removed those.
- **Console scripts were intentionally deferred.** If you add `[project.scripts]`
  later, wrap any `main()` that returns a non-int (notably
  `daily_player_upload.main()`, which returns a `(processed, overwritten)` tuple)
  so the console wrapper doesn't turn the return value into a failing exit code.
- **Dependencies still live in `requirements.txt`.** A future cleanup can move
  them into `pyproject.toml` `[project.dependencies]` (consider after plan 001's
  UTF-8 re-encoding of `requirements.txt` is confirmed DONE).
- **Reviewer focus**: confirm the local-`Data/` fallback still resolves to the
  repo root (Step 3), that `git mv` preserved history (`git log --follow` on a
  moved file), and that no logic changed inside any moved module beyond the
  import and `PROJECT_ROOT` lines (`git diff` should show only those).
</content>
</invoke>
