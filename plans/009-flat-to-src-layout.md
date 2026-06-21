# Plan 009: Convert the flat module layout to a `src/bigdataball/` package

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 198d5b9..HEAD -- '*.py' pytest.ini .github/workflows/test.yml`
> If any of the listed `.py` files, `pytest.ini`, or the workflow changed
> since this plan was written, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (but see "Maintenance notes" — landing this rebases the file paths of plans 003–008)
- **Category**: tech-debt
- **Planned at**: commit `a852503`, 2026-06-21 (refreshed for plan 005's merge `#24`; prior refreshes `198d5b9` 2026-06-20, `8bf4ce0` 2026-06-18; original `a91aac1` 2026-06-17). **Major refresh:** plan 005 added a new `paths.py` module and consolidated every per-script `PROJECT_ROOT`/`Data/`-fallback into `paths.resolve_base_data_path()`. Consequences for this plan, all handled below: (1) there are now **15** runtime modules to move, not 14 — `paths.py` is the new one; (2) nine modules now `import paths` and must be converted to `from . import paths` (Step 2); (3) the `__file__`-based path-resolution fix (Step 3) now applies to a **single** line in `paths.py`, not nine files; (4) plan 005 added `tests/test_paths.py` (2 tests) → total test count is now **18**.

## Why this matters

The repo is a flat collection of 15 top-level `.py` modules that import each
other by bare name (`import mappings`, `from auth_manager import ...`). A flat
layout makes the importable code indistinguishable from scripts, config, and
tests at the repo root, lets tests accidentally import from the working
directory instead of an installed package, and has no single packaging
manifest. Moving to the standard **src layout** (`src/bigdataball/`) with a
`pyproject.toml` gives the project one installable package, a clean import
namespace, and a foundation for the later refactors (plans 005–008). This plan
is deliberately the **minimum** mechanical move: create the folder, move the
files, fix the imports and the one `__file__`-based path that breaks when files
move deeper, add `pyproject.toml`, and update the test/CI wiring. No logic
changes, no API changes, no new behavior.

## Current state

All 15 runtime modules live at the repo root (the 14 original modules plus
`paths.py`, added by plan 005). Each is an importable module; most are also
runnable directly (`if __name__ == "__main__"`). The cross-module import graph
(verified at commit `a852503`). Note that nine modules now also `import paths`
(added by plan 005) — these conversions are in Step 2:

```
paths.py                             (no internal imports — pure stdlib)
daily_player_upload.py               import mappings ; import paths
email_notifier.py:3                  import config
auth_manager.py:5                    import config
run_db_patch.py                      import mappings ; import paths
export_slate_averages_csv.py         import mappings ; import paths
export_slate_averages_vw.py          import mappings ; import paths
export_playoffs_slate_averages_vw.py import mappings ; import paths
verify_db_patch.py                   import mappings ; import paths
check_ingest_duplicates.py           import paths
create_summary_tables.py             import paths
drive_ingestion.py:5                 from auth_manager import authenticate_google_drive
drive_ingestion.py:6                 import config
daily_fantasy_log_upload.py          import paths ; import create_summary_tables
                                     import export_slate_averages_vw
                                     import export_playoffs_slate_averages_vw
                                     import export_slate_averages_csv
                                     import daily_player_upload
                                     import drive_ingestion
                                     import email_notifier
                                     import mappings
```

`config.py` and `mappings.py` have **no** internal imports.

**The critical gotcha — `__file__`-based path resolution.** As of plan 005 this
logic lives in exactly **one** place: `paths.py`. All nine data-touching scripts
now call `paths.resolve_base_data_path()` instead of computing their own
`PROJECT_ROOT`. The relevant code is `paths.py:17-18`:

```python
project_root = os.path.dirname(os.path.abspath(__file__))
return os.path.join(project_root, "Data")
```

Today `paths.py` sits at the repo root, so `project_root` **is** the repo root.
After the move to `src/bigdataball/paths.py`, `dirname(abspath(__file__))`
becomes `<repo>/src/bigdataball`, so the local fallback would resolve to
`<repo>/src/bigdataball/Data` instead of `<repo>/Data`. **This must be fixed** in
`paths.py` only, by walking up two extra directory levels (Step 3). No other
module contains a `PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))`
line any more — verify with
`grep -rn "os.path.dirname(os.path.abspath(__file__))" *.py` → the only match is
`paths.py:17`.

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
  `paths.__file__`. After the move, replace `import paths` with
  `from bigdataball import paths` in both functions (the `import paths` lines are
  local to each test body — there are two). The `paths.__file__`-based `expected`
  assertion keeps working because it derives `Data/` from the module's own
  location.
- `tests/helpers.py`, `tests/__init__.py` need no changes.
- **Total test count is 18** (10 check_ingest + 4 player_upload + 1 fantasy_upload +
  1 orchestrator_warnings + 2 paths). Plan 009 adds no tests and removes none; the
  executor should see 18 pass after the move.

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
| List package files | `ls src/bigdataball/` | the 15 modules + `__init__.py` |
| Confirm no stray root modules | `ls *.py` | `No such file or directory` (or only non-package files if any remain) |

## Scope

**In scope** (the only files you should create, move, or modify):

- Move (with `git mv`) these 15 files from repo root into `src/bigdataball/`:
  `auth_manager.py`, `check_ingest_duplicates.py`, `config.py`,
  `create_summary_tables.py`, `daily_fantasy_log_upload.py`,
  `daily_player_upload.py`, `drive_ingestion.py`, `email_notifier.py`,
  `export_playoffs_slate_averages_vw.py`, `export_slate_averages_csv.py`,
  `export_slate_averages_vw.py`, `mappings.py`, `paths.py`, `run_db_patch.py`,
  `verify_db_patch.py`
- Create `src/bigdataball/__init__.py` (empty)
- Create `pyproject.toml` (repo root)
- Edit `pytest.ini`
- Edit `.github/workflows/test.yml`
- Edit `tests/conftest.py`, `tests/test_check_ingest_duplicates.py`, `tests/test_paths.py`
- Edit the import lines and `PROJECT_ROOT` lines inside the moved modules (per
  the tables above)
- Edit the documentation command blocks in `CLAUDE.md` and
  `.github/copilot-instructions.md` (Step 9 — command snippets only)
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

Create `src/bigdataball/` and `git mv` all 15 in-scope modules into it. Then
create an empty `src/bigdataball/__init__.py`.

```bash
mkdir -p src/bigdataball
git mv auth_manager.py check_ingest_duplicates.py config.py \
       create_summary_tables.py daily_fantasy_log_upload.py daily_player_upload.py \
       drive_ingestion.py email_notifier.py export_playoffs_slate_averages_vw.py \
       export_slate_averages_csv.py export_slate_averages_vw.py mappings.py \
       paths.py run_db_patch.py verify_db_patch.py src/bigdataball/
touch src/bigdataball/__init__.py
```

**Verify**: `ls src/bigdataball/` → lists the 15 modules plus `__init__.py`.
`ls *.py` at repo root → `No such file or directory` (no module files left at
root). `python -m pytest -q` will FAIL here (imports not yet fixed) — that is
expected; do not try to fix tests yet.

### Step 2: Convert cross-module imports to package-relative imports

Edit the moved files so every internal import becomes a relative import. The
module-reference name used elsewhere in each file is unchanged — only the
`import` line changes. Make exactly these replacements:

- `src/bigdataball/daily_player_upload.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/email_notifier.py`: `import config` → `from . import config`
- `src/bigdataball/auth_manager.py`: `import config` → `from . import config`
- `src/bigdataball/run_db_patch.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/export_slate_averages_csv.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/export_slate_averages_vw.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/export_playoffs_slate_averages_vw.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/verify_db_patch.py`: `import mappings` → `from . import mappings`; `import paths` → `from . import paths`
- `src/bigdataball/check_ingest_duplicates.py`: `import paths` → `from . import paths`
- `src/bigdataball/create_summary_tables.py`: `import paths` → `from . import paths`
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

**Verify**: `grep -rn -E "^import (mappings|paths|config|create_summary_tables|export_[a-z_]+|daily_player_upload|drive_ingestion|email_notifier)$|^from (auth_manager|config|mappings) import" src/bigdataball/` → **no matches** (all internal imports are now relative). The `export_[a-z_]+` branch matches all three export modules (`export_slate_averages_vw`, `export_playoffs_slate_averages_vw`, `export_slate_averages_csv`), not just a bare `export_`.

> **Expected behavior after this step — NOT a bug to "fix".** Once the internal
> imports are relative, running a module by its file path
> (`python src/bigdataball/daily_player_upload.py`) will raise
> `ImportError: attempted relative import with no known parent package`. This is
> correct and intended. From here on, every module must be run as
> `python -m bigdataball.<module>` (or exercised via the test suite). Do **not**
> revert to bare/absolute imports to make direct file execution work — that
> defeats the package layout. Step 9 updates the docs to the `-m` form.

### Step 3: Fix the `__file__`-based project-root resolution (the critical gotcha)

As of plan 005 this logic lives in exactly **one** file: `paths.py`. The other
modules call `paths.resolve_base_data_path()` and need no path edits. In
`src/bigdataball/paths.py` the `Data/` fallback (currently `paths.py:17-18`) is:

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

Edit **only** `paths.py`. Do not add this fix anywhere else — no other module
computes a project root from `__file__` any more.

**Verify**:
- `grep -rn "os.path.dirname(os.path.abspath(__file__))" src/bigdataball/` → matches **only** `paths.py` (and that line is now the inner expression of the triple-dirname replacement). To confirm the fix landed, the next grep is authoritative.
- `grep -rln "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))" src/bigdataball/` → lists exactly **one** file: `src/bigdataball/paths.py`.

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

Three test artifacts reference modules by bare name through `importlib`/`sys.modules`.
Prefix them all with `bigdataball.`:

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

**`tests/test_paths.py`** (added by plan 005): each of its two test functions has
a local `import paths` line. Change both to `from bigdataball import paths`. The
`paths.resolve_base_data_path()` and `paths.__file__` references on the following
lines stay unchanged — they resolve through the `paths` name either way.

Do **not** change the `sys.argv = ["check_ingest_duplicates.py", ...]` lines —
those are the simulated program name (`argv[0]`) and have no import meaning.
Do **not** change `tests/test_daily_player_upload.py` or `tests/test_daily_fantasy_log_upload.py` — they use fixtures via injection and `from tests.helpers`, which remain valid.

**Verify**: `grep -rn "import_module(\"daily_player_upload\")\|import_module(\"daily_fantasy_log_upload\")\|import_module(\"check_ingest_duplicates\")" tests/` → **no matches** (all now carry the `bigdataball.` prefix).
Also: `grep -n '"drive_ingestion"' tests/conftest.py` → **no matches** (key renamed to `"bigdataball.drive_ingestion"`).
Also: `grep -n "^    import paths$" tests/test_paths.py` → **no matches** (both converted to `from bigdataball import paths`).

### Step 7: Import smoke test (all 15 modules)

With the package installed (Step 4) confirm every module imports cleanly under
the package namespace, including the relative imports. The command below is a
single pure-Python invocation (no shell-specific syntax — works on Windows,
macOS, and Linux): it creates its own throwaway data dir with
`tempfile.mkdtemp()` and points `BIGDATABALL_DATA_DIR` at it *before* importing,
so the two modules that `os.makedirs(...)` at import time don't write into the
repo:

```bash
python -c "import os, tempfile, importlib; os.environ['BIGDATABALL_DATA_DIR'] = tempfile.mkdtemp(); [importlib.import_module('bigdataball.'+m) for m in ['auth_manager','check_ingest_duplicates','config','create_summary_tables','daily_fantasy_log_upload','daily_player_upload','drive_ingestion','email_notifier','export_playoffs_slate_averages_vw','export_slate_averages_csv','export_slate_averages_vw','mappings','paths','run_db_patch','verify_db_patch']]; print('ALL IMPORTS OK')"
```

**Verify**: prints `ALL IMPORTS OK`, exit 0. If any module raises
`ImportError`/`ModuleNotFoundError`, a relative import in Step 2 was missed —
fix it and re-run.

### Step 8: Run the full test suite

**Verify**: `python -m pytest -q` → all **18 tests** pass, exit 0 (10
`test_check_ingest_duplicates`, 4 `test_daily_player_upload`, 1
`test_daily_fantasy_log_upload`, 1 `test_orchestrator_warnings`, 2 `test_paths`). This plan adds no tests and removes none — if
the count differs, something was moved or shadowed. If any test errors with a
`ModuleNotFoundError` for `bigdataball.*` or `tests.*`, re-check Steps 5–6.

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
  `python -m bigdataball.<module>` substitution to any runnable command snippets.

Also update the in-code "rebuild derived data next" message in
`src/bigdataball/check_ingest_duplicates.py` (the print block near the original
lines 267–272) that lists `create_summary_tables.py, export_slate_averages_vw.py,
...` — change those `.py` names to the `python -m bigdataball.<module>` form so
the on-screen instruction stays accurate. This is a string-literal edit only; do
not change surrounding logic.

**Verify**: `grep -rn "python [a-z_]*\.py" CLAUDE.md .github/copilot-instructions.md` → **no matches** (all converted to `python -m bigdataball.`). `python -m pytest -q` still passes.

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
- The import smoke test in Step 7 covers the 12 modules not directly imported by
  the test suite (orchestrator, exports, etc.).
- Structural pattern to follow if any fixture needs adjusting:
  `tests/conftest.py`'s existing `player_upload` fixture.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `ls src/bigdataball/__init__.py` exists; all 15 modules are under `src/bigdataball/`; `ls *.py` at repo root returns none.
- [ ] `pip install -e .` exits 0.
- [ ] `grep -rn -E "^import (mappings|paths|config|create_summary_tables|daily_player_upload|drive_ingestion|email_notifier|export_[a-z_]+)$|^from (auth_manager|config|mappings) import" src/bigdataball/` returns no matches (all internal imports relative — same pattern as Step 2's verify).
- [ ] `grep -rln "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))" src/bigdataball/` lists exactly one file, `src/bigdataball/paths.py` (the only `Data/`-fallback path-resolution, deepened per Step 3).
- [ ] Step 7 import smoke test prints `ALL IMPORTS OK`.
- [ ] `python -m pytest -q` exits 0 with exactly 18 tests passing.
- [ ] `grep -rn "python [a-z_]*\.py" CLAUDE.md .github/copilot-instructions.md` returns no matches.
- [ ] CI workflow `.github/workflows/test.yml` runs `pip install -e .` before the tests (see Step 10).
- [ ] No files outside the in-scope list are modified (`git status`).
- [ ] `plans/README.md` status row for 009 updated to DONE.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any in-scope `.py` file, `pytest.ini`, or the workflow
  changed since commit `8bf4ce0`, and the "Current state" excerpts no longer
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

- **This plan rebases the file paths of every other plan.** Plans 003–008 in
  `plans/` reference root-level files (e.g. `daily_fantasy_log_upload.py`).
  After 009 lands, those same files live at `src/bigdataball/...`. Their logic,
  line numbers, and excerpts are otherwise unaffected (009 only moves files and
  changes import lines + the `PROJECT_ROOT` expression). When executing 003–008
  next, prepend `src/bigdataball/` to their in-scope paths. The `plans/README.md`
  dependency notes have been updated to flag this.
- **Plan 005 (centralize data-path resolution) supersedes Step 3's fix.** When
  005's `paths.resolve_base_data_path()` is introduced, it must compute the repo
  root from `src/bigdataball/` depth (three `dirname()` levels), and the
  per-file `PROJECT_ROOT` triple-`dirname` expressions added here get replaced by
  calls into that module. Don't leave both.
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
