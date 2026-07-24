# Plan 020: Split the pipeline orchestrator out of `daily_fantasy_log_upload.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 8c8bfc4..HEAD -- src/bigdataball/daily_fantasy_log_upload.py src/bigdataball/daily_player_upload.py tests/conftest.py tests/test_daily_fantasy_log_upload.py tests/test_orchestrator_warnings.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `8c8bfc4`, 2026-07-24

## Why this matters

`src/bigdataball/daily_fantasy_log_upload.py` does two unrelated jobs in one
`main()`: (1) it ingests DFS fantasy-log `.xlsx` files into `fantasy_logs`
(the inline loop), and (2) it orchestrates the **entire** daily pipeline —
Drive download, player-box-score upload, the fantasy ingestion, summary-table
rebuild, three slate-view exports, CSV export, and the notification email.
The file's name describes only the first job, so the codebase docs repeatedly
warn "this is the orchestrator despite its name" (`docs/codebase/CONCERNS.md:9`,
`CLAUDE.md:33`, `.github/copilot-instructions.md:139`). It is also the
highest-churn, riskiest file in the repo (`CLAUDE.md:55`).

This plan separates the two concerns so each module does one thing, matching
the shape of `daily_player_upload.py` (a focused ingestion module that is
*called by* the orchestrator):

- `daily_fantasy_log_upload.py` becomes **fantasy-log ingestion only** — same
  role as `daily_player_upload.py`. Its `main()` returns a counts-plus-errors
  tuple `(processed, overwritten, dropped, errors)`.
- A **new** `daily_pipeline.py` becomes the standalone orchestrator that calls
  every stage (including `daily_fantasy_log_upload.main()`) and sends the
  email.

After this lands, the file names match their roles, the orchestrator is a
small readable sequence of stage calls, and each half is independently
testable at its own level.

**This is a behavior-preserving refactor.** In particular, the end-of-run
notification email must be byte-for-byte identical to today's for the same
inputs — same `SUCCESS` / `COMPLETED WITH ERRORS` subject, same body, same
`(With Warnings)` blocks. The maintainer relies on the email subject to decide
whether a run needs attention, so a per-file fantasy-log failure that produces
`COMPLETED WITH ERRORS` today **must still** produce `COMPLETED WITH ERRORS`
after the split. That is why the ingestion `main()` returns a **4th element**
(a list of per-file error strings) rather than swallowing them — see
"Preserving the error-email behavior" below.

> **Deployment hazard — read before starting and echo in your PR description.**
> The maintainer's Windows Task Scheduler job currently runs
> `python -m bigdataball.daily_fantasy_log_upload` as the *whole pipeline*
> (`docs/codebase/INTEGRATIONS.md:48`). After this change that command ingests
> fantasy logs **only** — no Drive download, no summary, no email. The
> scheduled task MUST be repointed to `python -m bigdataball.daily_pipeline`.
> This is host-side config not in the repo; you cannot change it. Call it out
> loudly in the PR body so the maintainer updates the scheduled task.

## Current state

### The module being split — `src/bigdataball/daily_fantasy_log_upload.py`

Today it is 481 lines. Its structure (line anchors at commit `8c8bfc4`):

- **Lines 1–7** — stale header comment that opens `# main.py`.
- **Lines 8–21** — imports. Note it imports the whole pipeline:
  `create_summary_tables`, `export_slate_averages_vw`,
  `export_playoffs_slate_averages_vw`, `export_slate_averages_csv`,
  `daily_player_upload`, `drive_ingestion`, `email_notifier`, plus `mappings`,
  `paths`, `pandas`, `sqlalchemy`, `glob`, `os`, `datetime`.
- **Lines 24–38** — config: `BASE_DATA_PATH`, `NEW_FILES_FOLDER`
  (`Daily_Fantasy_Logs`), `PROCESSED_FOLDER` (`Archived_Fantasy_Logs`),
  `DB_PATH`, `LOGS_TABLE_NAME = "fantasy_logs"`,
  `PLAYERS_TABLE_NAME = "dim_players"`, `engine`.
- **Lines 41–60** — `ensure_unique_index()`.
- **Lines 63–78** — `initialize_database()`.
- **Lines 81–476** — `main()`, which interleaves BOTH jobs:
  - lines 88: `pipeline_errors = []` (the run-level error accumulator)
  - lines 90–98: STEP 0 Drive ingestion (`drive_ingestion.main()`), try/except → `pipeline_errors`
  - lines 100–115: STEP 1 player upload (`daily_player_upload.main()`), unpacks `(player_logs_count, player_logs_overwritten, absence_rows_count)`
  - lines 117–127: STEP 2 `initialize_database()` in try/except → `pipeline_errors`
  - lines 129–167: pre-load existing `(PLAYER_ID, DATE)` keys (with the plan-014 `Int64` normalization). Non-"no such table" DB error branch does `return` (line 167).
  - lines 169–366: **the fantasy-log ingestion loop** — read `.xlsx`, sanitize/rename columns, standardize names, int-cast IDs (drop + count missing), dedup, learn players, `to_sql` append, `ensure_unique_index()`, archive the file. Accumulates `fantasy_logs_count`, `fantasy_logs_overwritten`, `fantasy_rows_dropped`. **The per-file `except` at lines 359–364 appends to `pipeline_errors` and `break`s** (this is the error-email behavior that must be preserved — see below).
  - lines 370–415: summary + three exports, each try/except → `pipeline_errors`
  - lines 419–476: build + send the notification email (success/error, "(With Warnings)" blocks for dropped rows and unmatched DK players, append `todo_mappings.txt`)
- **Lines 479–480** — `if __name__ == "__main__": main()`.

The seam: **lines 90–115 and 370–476 are orchestration** (they belong in the
new file); **lines 117–366 are fantasy-log ingestion** (they stay, and become
the whole of the new ingestion `main()`). The one wire that crosses the seam is
`pipeline_errors`: the fantasy loop's per-file `except` writes to it today, so
the split must route those messages back to the orchestrator (see next
section).

### Preserving the error-email behavior (the key design point)

Today the fantasy loop lives inside the orchestrator, so its per-file `except`
(lines 359–364) writes straight into `pipeline_errors`:

```python
        except Exception as e:
            error_msg = f"ERROR processing {file_name}: {e}"
            print(f"\n*** {error_msg} ***")
            print("Script will stop. The failed file was NOT moved.")
            pipeline_errors.append(error_msg)
            break
```

Because that message lands in `pipeline_errors`, the run's email subject becomes
`BigDataBall Pipeline: COMPLETED WITH ERRORS [date]` and the body lists the
failing file. **This behavior must be preserved.** When the loop moves into the
ingestion module, `pipeline_errors` is no longer in scope there — so the
ingestion `main()` collects its per-file errors into a **local `errors` list**
and **returns it as a 4th tuple element**. The orchestrator then does
`pipeline_errors.extend(fantasy_errors)`, so the exact same `error_msg` string
reaches the exact same email path, unchanged. No behavior is lost and there is
no "escape hatch" — surfacing the error *is* the design.

> **Note on `daily_player_upload.py` (answers a question raised in review):**
> The player-upload module already `print`s + `break`s on a per-file error and
> returns a plain 3-tuple, so a per-file player error is **already** invisible
> in the email (it produces a `SUCCESS` run today). This plan does **not**
> change that — `daily_player_upload.py` is out of scope and its behavior is
> preserved by leaving it untouched. The result is that the two ingestion
> modules keep their *existing, different* error-surfacing behavior (fantasy
> surfaces per-file errors; player does not). Making player-upload also surface
> per-file errors would be a separate, opt-in enhancement (same 4-tuple
> mechanism) and is intentionally NOT bundled here. If you were told to also
> surface player-upload errors, treat that as a scope change and STOP to
> confirm.

### The exemplar to mirror — `src/bigdataball/daily_player_upload.py`

This is the target *shape* for the trimmed `daily_fantasy_log_upload.py` (a
focused ingestion module with a bare `initialize_database()`, a no-files
short-circuit, a `raise` on DB error, and a tuple return). Key structural facts
(line anchors at `8c8bfc4`):

- Imports only what ingestion needs: `pandas`, `sqlalchemy` (`create_engine`,
  `text`), `glob`, `os`, `absence_ingestion`, `mappings`, `paths` — **no**
  orchestration imports, **no** `email_notifier`, **no** `datetime`
  (`daily_player_upload.py:9-15`).
- `main()` starts by calling `initialize_database()` bare (line 79) — no
  try/except wrapper; if it raises, the caller (orchestrator) catches it.
- No-files short-circuit returns a zero tuple immediately
  (`daily_player_upload.py:113-115`).
- On a non-"no such table" DB error while pre-loading, it **`raise`s**
  (`daily_player_upload.py:105-108`) rather than `return`ing — so the caller's
  try/except records the failure.
- Per-file errors inside the loop **`print` + `break`** (`daily_player_upload.py:295-298`).
  (Fantasy will differ here: it must also record the message — see above.)
- `main()` **returns a tuple** — `(processed_count, overwritten_count,
  absences_count)` (`daily_player_upload.py:302`).
- Ends with `if __name__ == "__main__": main()`.

> A tuple return does **not** prevent running the module as
> `python -m bigdataball.<module>` — the `if __name__ == "__main__": main()`
> line discards the return value. (Tuple returns only matter for
> `[project.scripts]` console-script wrappers, which setuptools calls as
> `sys.exit(main())`; the repo deliberately has none — `STRUCTURE.md:53`. This
> plan adds none.) So both the ingestion module (4-tuple) and the orchestrator
> (`None`) remain valid `python -m` entrypoints.

### How the orchestrator already calls a sibling ingestion module

The player-upload stage in the current combined `main()` is the pattern the new
fantasy-upload stage extends (`daily_fantasy_log_upload.py:100-115`):

```python
    # --- STEP 1: Run Player Log Uploads (Box Scores) ---
    print("\n=== STARTING PIPELINE: PLAYER LOGS ===")
    player_logs_count = 0
    player_logs_overwritten = 0
    absence_rows_count = 0
    try:
        result = daily_player_upload.main()
        if isinstance(result, tuple):
            player_logs_count, player_logs_overwritten, absence_rows_count = result
        else:
            player_logs_count = result or 0
    except Exception as e:
        error_msg = f"CRITICAL ERROR in Player Upload: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
    print("=== PLAYER LOGS COMPLETE ===\n")
```

### Repo conventions that apply

- Package-relative imports inside `src/bigdataball/`: `from . import paths`,
  `from . import daily_player_upload` (`docs/codebase/CONVENTIONS.md:22-24`).
- Double-quoted strings, 4-space indent, section-banner comments
  (`# --- N. Title ---`) (`docs/codebase/CONVENTIONS.md:14-18`).
- Print-based logging, no `logging` module (`docs/codebase/CONVENTIONS.md:53`).
- Modules are run as `python -m bigdataball.<module>`; there is intentionally
  no `main.py` / console-script entry (`docs/codebase/STRUCTURE.md:53`).
- Test isolation is the env-seam / fresh-import pattern in `tests/conftest.py`
  (`monkeypatch.setenv("BIGDATABALL_DATA_DIR", ...)` → `sys.modules.pop` →
  `importlib.import_module`, then `engine.dispose()` on teardown)
  (`docs/codebase/TESTING.md:49-52`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install package (editable) | `pip install -e .` | exit 0 |
| Install dev deps | `pip install -r requirements-dev.txt` | exit 0 |
| Import smoke (orchestrator) | `python -c "import bigdataball.daily_pipeline"` | exit 0, no output |
| Import smoke (ingestion) | `python -c "import bigdataball.daily_fantasy_log_upload as m; print(m.main.__doc__)"` | exit 0 |
| One test file | `python -m pytest -q tests/test_daily_fantasy_log_upload.py` | all pass |
| One test file | `python -m pytest -q tests/test_orchestrator_warnings.py` | all pass |
| Full suite | `python -m pytest -q` | all pass (was 68 before this plan; expect 70 after — see Test plan) |

If `pip install -e .` was already run in this environment, `python -m pytest -q`
works directly. If imports fail with `ModuleNotFoundError: bigdataball`, run
`pip install -e .` first (or the `pytest.ini` `pythonpath = src` covers pytest,
but the bare `python -c` smokes need the editable install or `PYTHONPATH=src`).

## Scope

**In scope** (the only files you should modify or create):

- `src/bigdataball/daily_fantasy_log_upload.py` — trim to ingestion-only.
- `src/bigdataball/daily_pipeline.py` — **create**: the new orchestrator.
- `tests/conftest.py` — simplify `fantasy_upload`; add an `orchestrator` fixture.
- `tests/test_daily_fantasy_log_upload.py` — drop the email-suppression
  autouse fixture; adjust tests (details in Test plan).
- `tests/test_orchestrator_warnings.py` — repoint to the `orchestrator` fixture.
- `tests/test_daily_pipeline.py` — **create**: orchestrator-level tests.
- Docs (Step 6): `CLAUDE.md`, `.github/copilot-instructions.md`,
  `docs/codebase/ARCHITECTURE.md`, `docs/codebase/STRUCTURE.md`,
  `docs/codebase/CONVENTIONS.md`, `docs/codebase/CONCERNS.md`,
  `docs/codebase/TESTING.md`, `docs/codebase/INTEGRATIONS.md`,
  `plans/README.md`.

**Out of scope** (do NOT touch, even though they look related):

- `src/bigdataball/daily_player_upload.py` — the exemplar; leave unchanged.
  Do NOT "make it symmetric" by adding error surfacing — that changes its
  behavior (see the note above).
- Any `create_summary_tables.py`, `export_*`, `drive_ingestion.py`,
  `email_notifier.py`, `absence_ingestion.py` logic — only their *call sites*
  move, their bodies do not change.
- The fantasy-ingestion loop's **internal logic** — column sanitization,
  rename maps, name standardization, int-casting/dropping, dedup, `to_sql`
  dtype, archiving. Move it **verbatim** (the only edit is re-homing the
  per-file `except`'s `pipeline_errors.append` to a local `errors` list — see
  Step 2). Do not "improve" anything else.
- The email body/subject wording and `todo_mappings.txt` logic — move verbatim
  into the orchestrator; do not reword.
- `pyproject.toml` / `pytest.ini` — no packaging changes needed (a new module
  in an existing package is auto-discovered).
- Do NOT rename `daily_fantasy_log_upload.py` on disk and do NOT add a
  backward-compat shim to it — the whole point is that it becomes
  ingestion-only.

## Git workflow

- Work on the current branch (`claude/pipeline-orchestrator-refactor-py5jq4`);
  do not create a new branch.
- Commit per logical unit (e.g. "extract orchestrator", "update tests",
  "update docs"). Match the repo's plain imperative commit style (see
  `git log --oneline -10`).
- Push and open a PR per the repository's PR instructions.

## Steps

Order matters: create the new orchestrator first (codebase still works because
the old `main()` is untouched), then trim the old file, then fix tests, then
docs. Between Step 1 and Step 2 the repo has two working orchestrators
(`daily_fantasy_log_upload.main()` and `daily_pipeline.main()`); Step 2 removes
the duplication.

### Step 1: Create `src/bigdataball/daily_pipeline.py` (the orchestrator)

Create a new file whose `main()` is the orchestration wrapper — everything the
current `daily_fantasy_log_upload.main()` does **except** the inline fantasy
loop, which becomes a single call to `daily_fantasy_log_upload.main()`.

Target shape (fill the stage bodies by moving the corresponding blocks from the
current `daily_fantasy_log_upload.py` **verbatim** — same strings, same
counters, same comments):

```python
# daily_pipeline.py
# Whole-pipeline orchestrator for the BigDataBall NBA DFS data pipeline.
# Runs every stage in order and sends the end-of-run notification email:
#   Drive ingestion -> player box-score upload -> fantasy-log upload
#   -> summary tables -> slate views (regular + playoffs) -> CSV export -> email
# Each stage's errors are collected so one failure doesn't abort the rest.
import os
from datetime import datetime

from . import create_summary_tables
from . import export_slate_averages_vw
from . import export_playoffs_slate_averages_vw
from . import export_slate_averages_csv
from . import daily_player_upload
from . import daily_fantasy_log_upload
from . import drive_ingestion
from . import email_notifier
from . import paths

# BASE_DATA_PATH is only needed here for the todo_mappings.txt worklist path.
BASE_DATA_PATH = paths.resolve_base_data_path()


def main():
    pipeline_errors = []

    # --- STEP 0: Run Google Drive Ingestion ---
    # (move lines 90-98 of the old daily_fantasy_log_upload.py verbatim)

    # --- STEP 1: Run Player Log Uploads (Box Scores) ---
    # (move lines 100-115 verbatim; keeps player_logs_count / _overwritten /
    #  absence_rows_count)

    # --- STEP 2: Run Fantasy Log Upload ---
    print("\n=== STARTING PIPELINE: FANTASY LOGS ===")
    fantasy_logs_count = 0
    fantasy_logs_overwritten = 0
    fantasy_rows_dropped = 0
    fantasy_errors = []
    try:
        result = daily_fantasy_log_upload.main()
        (
            fantasy_logs_count,
            fantasy_logs_overwritten,
            fantasy_rows_dropped,
            fantasy_errors,
        ) = result
    except Exception as e:
        error_msg = f"CRITICAL ERROR in Fantasy Upload: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
    # Per-file fantasy errors are surfaced to the same run-level list the inline
    # loop used to write to, so the notification email keeps its exact prior
    # behavior (a per-file failure -> COMPLETED WITH ERRORS).
    pipeline_errors.extend(fantasy_errors)
    print("=== FANTASY LOGS COMPLETE ===\n")

    # --- Summary + exports ---
    # (move lines 370-415 verbatim: summary, slate vw, playoffs vw, csv;
    #  keep unmatched_dk_players = [] and its assignment)

    # --- Send Notification ---
    # (move lines 419-476 verbatim: date_str, success/error subject+body,
    #  the two "(With Warnings)" blocks, todo_mappings.txt append)


if __name__ == "__main__":
    main()
```

Precise move instructions:

1. STEP 0: copy lines 90–98 of the old file unchanged.
2. STEP 1: copy lines 100–115 unchanged.
3. STEP 2: replace the old lines 117–366 (init + pre-load + loop) with the
   try/except-plus-`extend` block shown above. Note the **4-element** unpack and
   the `pipeline_errors.extend(fantasy_errors)` line — these are what preserve
   the error-email behavior.
4. Summary/exports: copy lines 370–415 unchanged (including
   `unmatched_dk_players = []`).
5. Email: copy lines 419–476 unchanged. It references `BASE_DATA_PATH` (defined
   at module top), `player_logs_count`, `player_logs_overwritten`,
   `absence_rows_count`, `fantasy_logs_count`, `fantasy_logs_overwritten`,
   `fantasy_rows_dropped`, `unmatched_dk_players` — all now in scope.

Do **not** give `daily_pipeline.py` an `engine`, `DB_PATH`, `LOGS_TABLE_NAME`,
`ensure_unique_index`, or `initialize_database` — it does no direct DB work.
`BASE_DATA_PATH` is the only config it needs (for `todo_mappings.txt`).

**Verify**: `python -c "import bigdataball.daily_pipeline"` → exit 0, no output.
(The old file is still intact, so nothing else is broken yet.)

### Step 2: Trim `daily_fantasy_log_upload.py` to ingestion only

Rewrite the file so it mirrors `daily_player_upload.py`. Keep the config block,
`ensure_unique_index()`, and `initialize_database()` **unchanged**. Replace
`main()` with an ingestion-only version built from the old lines 117–366.

1. **Header comment (lines 1–7)**: replace the stale `# main.py` block with an
   accurate one, e.g.:
   ```python
   # daily_fantasy_log_upload.py
   # Ingest daily DraftKings fantasy-log .xlsx files into the fantasy_logs table.
   # Clean/rename columns, standardize player names, de-duplicate against existing
   # (PLAYER_ID, DATE) rows, learn new players into dim_players, and archive each
   # processed file. main() returns (processed, overwritten, dropped, errors) and
   # is called by daily_pipeline.py (the whole-pipeline orchestrator).
   ```

2. **Imports (lines 8–21)**: reduce to what ingestion uses. Keep:
   ```python
   import pandas as pd
   from sqlalchemy import create_engine, text, Integer
   import glob
   import os
   from . import mappings
   from . import paths
   ```
   **Remove**: `create_summary_tables`, `export_slate_averages_vw`,
   `export_playoffs_slate_averages_vw`, `export_slate_averages_csv`,
   `daily_player_upload`, `drive_ingestion`, `email_notifier`, and
   `from datetime import datetime`. (`Integer` stays — it's used in the
   `to_sql` dtype at old line 328–332.)

3. **Config (lines 24–38), `ensure_unique_index` (41–60),
   `initialize_database` (63–78)**: leave exactly as-is.

4. **Rewrite `main()`** to contain only the ingestion work:
   - Start with `initialize_database()` **bare** (no try/except — the
     orchestrator wraps the call). This replaces the old STEP 2 block
     (old lines 117–127).
   - **Define a local error accumulator** near the top of `main()`, before the
     loop: `errors = []`. This replaces the role `pipeline_errors` played for
     the loop's per-file `except`.
   - Then the pre-load block: move old lines 129–167 **but** change the
     non-"no such table" error branch from `return` (old line 167) to
     `raise e`, mirroring `daily_player_upload.py:108`, so the orchestrator's
     try/except records it. The `"no such table"` branch stays (creates the
     empty DataFrame).
   - Add the no-files short-circuit like the exemplar. After computing
     `files_to_process = sorted(glob.glob(...))`:
     ```python
     if not files_to_process:
         print("No new files found to process.")
         return 0, 0, 0, []
     print(f"Found {len(files_to_process)} new file(s) to process...")
     existing_log_keys = set(existing_logs_df["log_key"])
     ```
     (This replaces the old lines 172–179 which used the
     `if files_to_process else set()` guard; the early return makes the guard
     unnecessary. Note the 4-element zero tuple: `0, 0, 0, []`.)
   - Move the loop body (old lines 181–366) verbatim, including the
     `fantasy_logs_count` / `fantasy_logs_overwritten` / `fantasy_rows_dropped`
     counters — **with one required change**: the per-file `except` at old
     lines 359–364 appends to `pipeline_errors`, which no longer exists in the
     ingestion-only `main()`. **Re-home that append to the local `errors`
     list** (keep everything else about the `except` identical — the
     `error_msg` string, both prints, the `break`):
     ```python
             except Exception as e:
                 error_msg = f"ERROR processing {file_name}: {e}"
                 print(f"\n*** {error_msg} ***")
                 print("Script will stop. The failed file was NOT moved.")
                 errors.append(error_msg)
                 break
     ```
     This is the only line in the loop body that referenced an
     orchestration-half name; re-homing it (not deleting it) is what preserves
     the `COMPLETED WITH ERRORS` email.
   - End `main()` with:
     ```python
     print("\n--- All new files processed. ---")
     return fantasy_logs_count, fantasy_logs_overwritten, fantasy_rows_dropped, errors
     ```
     Delete the old post-loop code entirely (old line 368
     `print("\n--- Ingestion Phase Complete ---")` **and** the orchestration at
     old lines 370–476) — it now lives in `daily_pipeline.py`.

5. Keep `if __name__ == "__main__": main()` at the end.

**Verify**:
- `python -c "import bigdataball.daily_fantasy_log_upload as m; print(sorted(n for n in dir(m) if not n.startswith('__')))"`
  → the printed list must **not** contain `email_notifier`,
  `create_summary_tables`, `drive_ingestion`, `daily_player_upload`,
  `export_slate_averages_vw`, `datetime`. It must still contain `engine`,
  `main`, `ensure_unique_index`, `initialize_database`, `NEW_FILES_FOLDER`.
- `python -m pytest -q tests/test_daily_fantasy_log_upload.py` — will fail
  until Step 3/4 (the fixture/tests still assume the old shape). That is
  expected; proceed.

### Step 3: Update `tests/conftest.py`

The `fantasy_upload` fixture currently imports the combined module and stubs
Drive/Google/email because the module pulled those in. Now that
`daily_fantasy_log_upload` is pure ingestion, its fixture can be as simple as
`player_upload`. The orchestrator needs a new fixture that does the stubbing.

1. **Add** `bigdataball.daily_pipeline` to the `_FANTASY_DEPS` list (so it is
   popped/reimported fresh).

2. **Replace** the `fantasy_upload` fixture with a simple ingestion fixture
   modeled on `player_upload` (no Google/Drive/email stubbing, no email
   wrapper):
   ```python
   @pytest.fixture
   def fantasy_upload(tmp_path, monkeypatch):
       """Imports daily_fantasy_log_upload (ingestion only) fresh with
       BASE_DATA_PATH pointed at a temp dir. Returns the module; its engine,
       paths, and tables all live under tmp_path."""
       data_dir = tmp_path / "data"
       (data_dir / "Daily_Fantasy_Logs").mkdir(parents=True)
       (data_dir / "Archived_Fantasy_Logs").mkdir(parents=True)
       monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

       sys.modules.pop("bigdataball.daily_fantasy_log_upload", None)
       module = importlib.import_module("bigdataball.daily_fantasy_log_upload")

       yield module

       module.engine.dispose()
       sys.modules.pop("bigdataball.daily_fantasy_log_upload", None)
   ```

3. **Add** an `orchestrator` fixture that imports `daily_pipeline` with the
   stubbing the old `fantasy_upload` fixture had (keep the `_STUB_MODULES`
   dict and the reset loop). It must create all four input/archive dirs and
   dispose the engines of the sub-modules the orchestrator imports:
   ```python
   @pytest.fixture
   def orchestrator(tmp_path, monkeypatch):
       """Imports daily_pipeline (the orchestrator) fresh with BASE_DATA_PATH
       pointed at a temp dir. Stubs Google/Drive/SMTP deps. Returns the module."""
       data_dir = tmp_path / "data"
       (data_dir / "Daily_Fantasy_Logs").mkdir(parents=True)
       (data_dir / "Daily_Player_Logs").mkdir(parents=True)
       (data_dir / "Archived_Fantasy_Logs").mkdir(parents=True)
       (data_dir / "Archived_Player_Logs").mkdir(parents=True)
       monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

       for name in _FANTASY_DEPS:
           sys.modules.pop(name, None)

       stub_names_added = []
       for mod_name, attrs in _STUB_MODULES.items():
           if mod_name not in sys.modules:
               stub = types.ModuleType(mod_name)
               for attr, val in attrs.items():
                   setattr(stub, attr, val)
               sys.modules[mod_name] = stub
               stub_names_added.append(mod_name)

       module = importlib.import_module("bigdataball.daily_pipeline")

       # Default the email sender to a NO-OP so any orchestrator test that
       # drives main() without replacing send_email_alert itself cannot perform
       # real SMTP I/O. daily_pipeline.main() always calls send_email_alert at
       # the end, and config.EMAIL_ENABLED is hardcoded True, so a real send
       # would hang the sandbox (no network) with no timeout -- the same hazard
       # the plan-010 test file documents. Individual tests still monkeypatch
       # send_email_alert to capture the subject/body when they need to assert
       # on it (see test_daily_pipeline.py / test_orchestrator_warnings.py).
       monkeypatch.setattr(
           module.email_notifier, "send_email_alert", lambda *a, **kw: None
       )

       yield module

       # daily_pipeline has no engine of its own; dispose the sub-module engines
       # so Windows can delete the locked SQLite file before tmp cleanup.
       module.daily_fantasy_log_upload.engine.dispose()
       module.daily_player_upload.engine.dispose()
       for name in _FANTASY_DEPS:
           sys.modules.pop(name, None)
       for name in stub_names_added:
           sys.modules.pop(name, None)
   ```

**Verify**: `python -c "import tests.conftest"` from repo root with
`PYTHONPATH=.:src` → exit 0 (syntax check only; fixtures run under pytest).

### Step 4: Update `tests/test_daily_fantasy_log_upload.py` (ingestion tests)

These tests drive the now-pure ingestion `main()`, which returns a **4-tuple**.
Ingestion no longer sends email, so the email plumbing must go.

1. **Delete** the `_suppress_pipeline_email` autouse fixture (lines 9–16). The
   pure ingestion `main()` performs no SMTP send, so nothing to suppress, and
   `mod.email_notifier` no longer exists on the module (it would `AttributeError`).

2. Tests that only assert on DB row counts / columns / index — keep unchanged
   (they ignore `main()`'s return value):
   `test_dedup_across_files_in_one_run`, `test_unique_index_exists_on_fantasy_logs`,
   `test_single_file_loads_logs_and_learns_players`,
   `test_player_name_standardization_applied`, `test_unwanted_columns_are_dropped`,
   `test_date_stored_as_iso_format`, `test_player_id_stored_as_integer`,
   `test_rerun_same_file_no_duplicates_after_int_cast`.

3. `test_fractional_player_id_is_rejected_not_truncated` — the `count_rows == 1`
   assertion still holds. **Extend it** to also assert the per-file error is now
   returned (this is the ingestion-side proof that the error survives to be
   surfaced), and fix the docstring:
   ```python
   def test_fractional_player_id_is_rejected_and_error_returned(fantasy_upload):
       """A fractional PLAYER_ID (data corruption) must not be silently
       truncated into a different valid-looking player. feed_01 (valid) is
       ingested; feed_02's fractional id raises ValueError, which the ingestion
       loop catches -- recording the error and breaking -- so the corrupt row
       never lands AND the error is returned for the orchestrator to surface."""
       mod = fantasy_upload
       good = make_fantasy_rows([(1, "Alpha Player", "2025-11-01")])
       bad = make_fantasy_rows([(2.5, "Corrupt Player", "2025-11-02")])
       write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_01_good.xlsx"), good)
       write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_02_bad.xlsx"), bad)

       processed, overwritten, dropped, errors = mod.main()

       assert count_rows(mod.engine, "fantasy_logs") == 1
       assert len(errors) == 1
       assert "feed_02_bad.xlsx" in errors[0]
   ```

4. **Replace** `test_missing_player_id_row_dropped_counted_and_surfaced`
   (which asserted on the email) with an ingestion-level test that asserts on
   the DB and the returned tuple (the email half moves to Step 5):
   ```python
   def test_missing_player_id_row_dropped_and_counted(fantasy_upload):
       """A data row missing PLAYER_ID is not a valid player-game log: it is
       dropped (not inserted) and counted in the returned dropped count. No
       per-file error is raised for a droppable row, so errors is empty."""
       mod = fantasy_upload
       rows = make_fantasy_rows([
           (None, "Ghost Player", "2025-11-01"),  # missing PLAYER_ID -> dropped
           (1, "Alpha Player", "2025-11-02"),      # valid -> inserted
       ])
       write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

       processed, overwritten, dropped, errors = mod.main()

       assert count_rows(mod.engine, "fantasy_logs") == 1
       assert (processed, overwritten, dropped) == (1, 0, 1)
       assert errors == []
   ```

**Verify**: `python -m pytest -q tests/test_daily_fantasy_log_upload.py`
→ all pass.

### Step 5: Repoint `tests/test_orchestrator_warnings.py` and add `tests/test_daily_pipeline.py`

1. **`tests/test_orchestrator_warnings.py`**: change the single test's fixture
   argument from `fantasy_upload` to `orchestrator`. Its body already
   monkeypatches `mod.daily_player_upload.main`,
   `mod.create_summary_tables.run_summary_pipeline`,
   `mod.export_slate_averages_csv.run_slate_averages_smart_export`,
   `mod.export_slate_averages_vw.run_slate_averages_pipeline`,
   `mod.export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline`,
   and `mod.email_notifier.send_email_alert` — all of these are attributes of
   `daily_pipeline`, so no other change is needed. It reads
   `mod.BASE_DATA_PATH` for `todo_mappings.txt`, which `daily_pipeline` defines.
   Change only the function signature line:
   ```python
   def test_unmatched_uses_regular_season_not_playoffs(orchestrator, monkeypatch):
       mod = orchestrator
   ```

2. **Create `tests/test_daily_pipeline.py`** with **two** orchestrator-level
   tests. The first proves the dropped-rows warning path; the **second is the
   critical behavior-preservation test** — a per-file fantasy error must still
   produce a `COMPLETED WITH ERRORS` email:
   ```python
   def test_dropped_rows_surfaced_in_success_email(orchestrator, monkeypatch):
       """When fantasy ingestion reports dropped rows (but no errors), the
       success email must flag '(With Warnings)' and include the dropped line."""
       mod = orchestrator

       monkeypatch.setattr(mod.daily_player_upload, "main", lambda: (0, 0, 0))
       # 4-tuple: processed, overwritten, dropped, errors
       monkeypatch.setattr(
           mod.daily_fantasy_log_upload, "main", lambda: (1, 0, 1, [])
       )
       monkeypatch.setattr(
           mod.create_summary_tables, "run_summary_pipeline", lambda: None
       )
       monkeypatch.setattr(
           mod.export_slate_averages_vw, "run_slate_averages_pipeline", lambda: []
       )
       monkeypatch.setattr(
           mod.export_playoffs_slate_averages_vw,
           "run_playoffs_slate_averages_pipeline",
           lambda: None,
       )
       monkeypatch.setattr(
           mod.export_slate_averages_csv,
           "run_slate_averages_smart_export",
           lambda: None,
       )

       captured = {}
       monkeypatch.setattr(
           mod.email_notifier,
           "send_email_alert",
           lambda s, b: captured.update(subject=s, body=b),
       )

       mod.main()

       assert "subject" in captured, "email was never sent"
       assert "SUCCESS" in captured["subject"]
       assert "(With Warnings)" in captured["subject"]
       assert (
           "Fantasy Rows Dropped (missing PLAYER_ID/GAME_ID): 1" in captured["body"]
       )


   def test_per_file_fantasy_error_produces_errors_email(orchestrator, monkeypatch):
       """Behavior preservation: a per-file fantasy ingestion error (returned in
       the 4th tuple element) must still produce a 'COMPLETED WITH ERRORS' email
       listing the failing file -- exactly as the old inline loop did."""
       mod = orchestrator

       monkeypatch.setattr(mod.daily_player_upload, "main", lambda: (0, 0, 0))
       # Fantasy ingestion processed nothing but reports a per-file error.
       monkeypatch.setattr(
           mod.daily_fantasy_log_upload,
           "main",
           lambda: (0, 0, 0, ["ERROR processing bad_feed.xlsx: boom"]),
       )
       monkeypatch.setattr(
           mod.create_summary_tables, "run_summary_pipeline", lambda: None
       )
       monkeypatch.setattr(
           mod.export_slate_averages_vw, "run_slate_averages_pipeline", lambda: []
       )
       monkeypatch.setattr(
           mod.export_playoffs_slate_averages_vw,
           "run_playoffs_slate_averages_pipeline",
           lambda: None,
       )
       monkeypatch.setattr(
           mod.export_slate_averages_csv,
           "run_slate_averages_smart_export",
           lambda: None,
       )

       captured = {}
       monkeypatch.setattr(
           mod.email_notifier,
           "send_email_alert",
           lambda s, b: captured.update(subject=s, body=b),
       )

       mod.main()

       assert "subject" in captured, "email was never sent"
       assert "COMPLETED WITH ERRORS" in captured["subject"]
       assert "ERROR processing bad_feed.xlsx: boom" in captured["body"]
   ```
   No `tests.helpers` import is needed (ingestion is stubbed); the fixture is
   the only dependency.

**Verify**:
- `python -m pytest -q tests/test_orchestrator_warnings.py` → 1 passed.
- `python -m pytest -q tests/test_daily_pipeline.py` → 2 passed.
- `python -m pytest -q` → all pass. Expected count: **68 + 2** new
  `test_daily_pipeline.py` tests = **70**. (`test_daily_fantasy_log_upload.py`
  keeps its 10 tests — one replaced 1:1, one extended, none added net;
  `test_orchestrator_warnings` is repointed, not added.) If the count is not
  70, reconcile before proceeding.

### Step 6: Update documentation

Update every doc that calls `daily_fantasy_log_upload.py` the orchestrator /
main entry point, and add `daily_pipeline.py`. Exact targets (verify text
against the live file first — line numbers may have shifted):

1. **`CLAUDE.md`**:
   - "Build And Run" (around line 20): change the MAIN orchestrator command
     from `python -m bigdataball.daily_fantasy_log_upload` to
     `python -m bigdataball.daily_pipeline`.
   - Line ~33: replace "`daily_fantasy_log_upload.py` is the whole-pipeline
     orchestrator despite its name." with a sentence naming
     `daily_pipeline.py` as the orchestrator and `daily_fantasy_log_upload.py`
     as fantasy-log ingestion (parallel to `daily_player_upload.py`).
   - In the standalone-stages list (lines 36–48), add
     `python -m bigdataball.daily_fantasy_log_upload   # ingest DFS fantasy logs only`
     near the `daily_player_upload` line.
   - Line ~55 ("riskiest files"): update the description of
     `daily_fantasy_log_upload.py` from "orchestrator + inline fantasy-log
     loop" to "fantasy-log ingestion + dedup", and add `daily_pipeline.py` as
     the orchestrator if you keep a risk note.

2. **`.github/copilot-instructions.md`**:
   - Line 11: change the `daily_fantasy_log_upload.py` row from
     "Main entry point / orchestrator..." to a fantasy-log-ingestion
     description mirroring the `daily_player_upload.py` row (line 12). Add a
     new table row for `daily_pipeline.py` as the main entry point / orchestrator.
   - Line ~109: change `python -m bigdataball.daily_fantasy_log_upload` to
     `python -m bigdataball.daily_pipeline`.
   - Line ~139: delete/repurpose the "orchestrator despite its name" note.

3. **`docs/codebase/ARCHITECTURE.md`**: line 9 ("Orchestrated by
   `daily_fantasy_log_upload.py:main()`") → `daily_pipeline.py:main()`; the flow
   diagram comment "daily_fantasy_log_upload (inline loop)" (line 18) →
   "daily_fantasy_log_upload.main() # DFS logs -> fantasy_logs" and add a
   line noting `daily_pipeline.main()` orchestrates; update the "Resilient stage
   orchestration" and "Error Handling" evidence anchors (lines 49, 77) that
   point at `daily_fantasy_log_upload.py:80-347` to point at `daily_pipeline.py`.

4. **`docs/codebase/STRUCTURE.md`**: the module tree (lines 12–13) — change
   `daily_fantasy_log_upload.py` comment from "MAIN orchestrator (despite the
   name)" to "ingest DFS fantasy logs", and add a `daily_pipeline.py` entry
   ("MAIN orchestrator — runs the full pipeline"). Update the Entry Points
   table (lines 55–57): move the orchestrator row to `daily_pipeline.py` `main()`
   and re-describe `daily_fantasy_log_upload.py` as fantasy-log ingestion
   returning `(processed, overwritten, dropped, errors)`.

5. **`docs/codebase/CONVENTIONS.md`**: line 12 (stale `# main.py` header note)
   — the header is being fixed in Step 2, so update this to say the header was
   corrected; update the error-handling evidence at lines 49, 68 that anchor
   `daily_fantasy_log_upload.py:80-347` to `daily_pipeline.py`.

6. **`docs/codebase/CONCERNS.md`**: item 3 (line 9, "Orchestrator name vs.
   role") is now **resolved** — replace it with a note that the orchestrator
   was split into `daily_pipeline.py` (or remove the item and renumber).
   Update the churn note (line 40) if you wish (optional).

7. **`docs/codebase/TESTING.md`**: the test-file table (lines 25–33) — update
   `test_daily_fantasy_log_upload.py` description (still ingestion, count
   unchanged at 10), and add `test_daily_pipeline.py` (2 tests). Update the
   "68 passed" figures to **70**.

8. **`docs/codebase/INTEGRATIONS.md`**: line 26 (email evidence
   `daily_fantasy_log_upload.py:355-395`) → `daily_pipeline.py`; line 48
   (Windows Task Scheduler "runs `daily_fantasy_log_upload.py`") → note it must
   now run `daily_pipeline` (`python -m bigdataball.daily_pipeline`); line 62
   evidence anchor → `daily_pipeline.py`.

9. **`plans/README.md`**: the "Findings considered and rejected" bullet
   "Misleading orchestrator filename ... Not worth it" is now **actioned** —
   update that bullet to point at this plan, and set the plan 020 row to DONE
   (see Step 7).

**Verify**:
`grep -rn "orchestrator despite\|MAIN orchestrator (despite\|Main entry point / orchestrator" CLAUDE.md docs/ .github/copilot-instructions.md`
→ no matches (the "despite its name" framing is gone).

### Step 7: Update `plans/README.md` status row

Set the plan 020 row in the status table to DONE:

```
| 020  | Split the pipeline orchestrator out of `daily_fantasy_log_upload.py` | P2 | M | none | DONE | — |
```

and flip the "Misleading orchestrator filename" rejected-finding bullet to
reference plan 020 as the resolution.

**Verify**: `grep -n "020" plans/README.md` → shows the DONE row.

## Test plan

- **Existing tests preserved** (ingestion, in `test_daily_fantasy_log_upload.py`):
  the eight DB-count/column/index tests keep passing against the pure ingestion
  `main()` (they ignore the return value).
- **Extended ingestion test**: `test_fractional_player_id_is_rejected_and_error_returned`
  now also asserts the per-file error is in the returned `errors` list — the
  ingestion-side half of the behavior-preservation guarantee.
- **New ingestion test**: `test_missing_player_id_row_dropped_and_counted`
  asserts the dropped row is not inserted, that `main()` returns `(1, 0, 1, [])`
  — exercising the 4-tuple contract — and that a droppable row produces no
  error.
- **New orchestrator tests** (`test_daily_pipeline.py`, 2):
  - `test_dropped_rows_surfaced_in_success_email` — dropped rows → `SUCCESS`
    `(With Warnings)` email.
  - `test_per_file_fantasy_error_produces_errors_email` — **the critical
    behavior-preservation test**: a per-file fantasy error (returned as the 4th
    tuple element) → `COMPLETED WITH ERRORS` email listing the file. This is the
    regression guard for the maintainer's "email tells me if I need to look"
    workflow.
  Model both after `test_orchestrator_warnings.py` (same stubbing pattern, same
  `orchestrator` fixture).
- **Repointed test**: `test_orchestrator_warnings.py` now runs against
  `daily_pipeline` via the `orchestrator` fixture — proving the unmatched-DK
  worklist/email path survived the move verbatim.
- **Verification**: `python -m pytest -q` → all pass; total = prior 68 + 2 new
  = **70**.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -c "import bigdataball.daily_pipeline"` exits 0.
- [ ] `python -c "import bigdataball.daily_fantasy_log_upload as m; assert not hasattr(m, 'email_notifier') and not hasattr(m, 'create_summary_tables') and not hasattr(m, 'drive_ingestion'); assert callable(m.main)"` exits 0.
- [ ] `python -c "import bigdataball.daily_fantasy_log_upload as m, inspect; src = inspect.getsource(m.main); assert 'drive_ingestion' not in src and 'create_summary_tables' not in src and 'email_notifier' not in src"` exits 0 (no orchestration calls remain inside the ingestion `main()`).
- [ ] Ingestion `main()` returns a 4-tuple: `python -c "import bigdataball.daily_fantasy_log_upload as m, inspect; assert 'return fantasy_logs_count, fantasy_logs_overwritten, fantasy_rows_dropped, errors' in inspect.getsource(m.main)"` exits 0.
- [ ] Orchestrator forwards fantasy errors: `python -c "import bigdataball.daily_pipeline as m, inspect; assert 'pipeline_errors.extend(fantasy_errors)' in inspect.getsource(m.main)"` exits 0.
- [ ] `python -m pytest -q` exits 0; `test_daily_pipeline.py` (2 tests incl.
      `test_per_file_fantasy_error_produces_errors_email`) and the updated
      ingestion tests exist and pass; total is **70**.
- [ ] `grep -rn "daily_fantasy_log_upload" .github/workflows/` returns nothing
      (CI runs the test suite, not the module by name — confirms no CI ref
      needs changing).
- [ ] `grep -rn "orchestrator despite\|Main entry point / orchestrator" CLAUDE.md docs/ .github/` returns no matches.
- [ ] `grep -rn "daily_pipeline" CLAUDE.md docs/codebase/STRUCTURE.md .github/copilot-instructions.md` shows the new orchestrator named as the entry point in each. (Do NOT assert `daily_fantasy_log_upload` is absent from docs — it intentionally remains as the standalone fantasy-ingestion command in `CLAUDE.md`'s stage list; only the *orchestrator* framing moves to `daily_pipeline`.)
- [ ] `plans/README.md` has the plan 020 row marked DONE.
- [ ] `git status` shows only the in-scope files changed.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows `daily_fantasy_log_upload.py`,
  `daily_player_upload.py`, or the touched test files changed since commit
  `8c8bfc4` and the "Current state" excerpts/line anchors no longer match.
- The fantasy-ingestion loop body (old lines 181–366) references an
  orchestration-half name **other than** the single `pipeline_errors.append`
  in the per-file `except` that Step 2 tells you to re-home. It should
  otherwise be self-contained; if it is not, stop and report the dependency.
- After Step 5, the full-suite test count is not 70, or any test outside the
  in-scope files fails — a stage may have been moved with altered behavior.
- `daily_pipeline.main()` needs an `engine`/`DB_PATH`/table constant — it should
  not. If you find yourself adding one, you moved too much (some ingestion code
  came along); stop and re-split.
- You are tempted (or instructed) to change `daily_player_upload.py` to also
  surface per-file errors. That is a separate scope change — stop and confirm.
- You discover another caller (a script, cron, or CI job **inside the repo**)
  that invokes `python -m bigdataball.daily_fantasy_log_upload` expecting the
  full pipeline. The repo has none as of `8c8bfc4` (only host-side Windows Task
  Scheduler, which is out of repo); if one exists, report it.

## Maintenance notes

For whoever owns this code next:

- **Windows Task Scheduler must be repointed** to
  `python -m bigdataball.daily_pipeline`. This is the single operational action
  outside the repo; without it the daily job silently degrades to
  fantasy-ingestion-only. This is the top review item.
- **This is a behavior-preserving refactor** — the notification email is
  intentionally unchanged. A per-file fantasy-log failure still produces
  `COMPLETED WITH ERRORS`, because the ingestion `main()` returns its per-file
  error messages as a 4th tuple element and the orchestrator does
  `pipeline_errors.extend(fantasy_errors)`. The test
  `test_per_file_fantasy_error_produces_errors_email` is the regression guard;
  do not let a future change drop it.
- **Pre-existing asymmetry (documented, not changed here):**
  `daily_player_upload.py` does NOT surface its per-file errors — it `break`s
  and returns a 3-tuple, so a per-file player error yields a `SUCCESS` email.
  If the maintainer wants player-upload errors surfaced too, apply the same
  4-tuple pattern to `daily_player_upload.main()` and add
  `pipeline_errors.extend(player_errors)` in the orchestrator's STEP 1. That is
  a deliberate follow-up, not part of this plan.
- A reviewer should confirm the fantasy loop moved **verbatim** apart from the
  single `pipeline_errors.append` → `errors.append` re-home (diff the loop body
  against `8c8bfc4`'s lines 181–366), and that the email/`todo_mappings` block
  moved **verbatim**.
- The `improve` codebase docs (`docs/codebase/*`) and
  `.github/copilot-instructions.md` now describe `daily_pipeline.py` as the
  entry point; future doc refreshes should keep the two-module split.
