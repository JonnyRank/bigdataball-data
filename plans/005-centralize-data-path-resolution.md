# Plan 005: Centralize the duplicated data-path resolution into a single `paths` module

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- daily_player_upload.py daily_fantasy_log_upload.py create_summary_tables.py export_slate_averages_vw.py export_playoffs_slate_averages_vw.py export_slate_averages_csv.py run_db_patch.py verify_db_patch.py`
> Plans 002–004 modify the two upload scripts; this plan replaces the path block in all
> eight files. Compare the "Current state" excerpts against the live code before
> editing each file; on a mismatch in the path block, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 002 (pytest harness; this plan supersedes the inline env-var branch 002 added to the two upload scripts)
- **Category**: tech-debt
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

The data-directory resolution block is copy-pasted across eight scripts. `CLAUDE.md`
documents it as "duplicated per-file rather than centralized," and the copies have
already drifted (`config.py` hardcodes the path with no fallback; the two upload scripts
gained a `BIGDATABALL_DATA_DIR` override in plan 002 while the others have only the
two-branch form). A single source of truth removes the drift, makes the whole pipeline
redirectable to a temp/local directory (useful for testing and offline runs), and is a
prerequisite for cleanly testing the export/patch scripts later.

## Current state

Each of these files contains a variant of this block, computed at module import:

```python
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
```

Files and the line ranges of their block (verify against live code — plans 002+ shifted
some lines):
- `daily_player_upload.py:16-24` — note: plan 002 added an `BIGDATABALL_DATA_DIR` branch here.
- `daily_fantasy_log_upload.py:24-32` — note: plan 002 added the env branch here too.
- `create_summary_tables.py:9-17`
- `export_slate_averages_vw.py:21-26` — block is **inside** `run_slate_averages_pipeline()`.
- `export_playoffs_slate_averages_vw.py:21-26` — inside `run_playoffs_slate_averages_pipeline()`.
- `export_slate_averages_csv.py:23-27` — inside `run_slate_averages_smart_export()`.
- `run_db_patch.py:6-13`
- `verify_db_patch.py:6-11`

All derive further paths from `BASE_DATA_PATH` (e.g. `DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")`).
Those derived lines stay; only the resolution of `BASE_DATA_PATH` is centralized.

The tests added in plans 002–004 reload a script module after setting
`BIGDATABALL_DATA_DIR`; the new module must therefore **recompute** `BASE_DATA_PATH` at
each module import (i.e. call a function, not import a precomputed constant), so the
reload picks up the env var.

## Commands you will need

| Purpose      | Command                                                          | Expected on success |
|--------------|------------------------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile *.py`                                     | exit 0              |
| Run tests    | `python3 -m pytest -q`                                           | all pass            |
| Env redirect | `BIGDATABALL_DATA_DIR=/tmp/x python3 -c "import paths; print(paths.resolve_base_data_path())"` | `/tmp/x` |

## Scope

**In scope** (create one, modify eight):
- `paths.py` (create)
- `daily_player_upload.py`, `daily_fantasy_log_upload.py`, `create_summary_tables.py`,
  `export_slate_averages_vw.py`, `export_playoffs_slate_averages_vw.py`,
  `export_slate_averages_csv.py`, `run_db_patch.py`, `verify_db_patch.py` — replace the
  path-resolution block with a call to `paths.resolve_base_data_path()`.
- `tests/test_paths.py` (create)

**Out of scope** (do NOT touch):
- `config.py` — it hardcodes `BASE_DOWNLOAD_DIR` for Drive ingestion with intentionally
  different semantics (download targets, no fallback). Leave it; a follow-up can
  reconcile it. Do not change `drive_ingestion.py`.
- All derived path lines (`NEW_FILES_FOLDER`, `DB_PATH`, `CSV_EXPORT_DIR`, archive
  folders) — keep them, only their `BASE_DATA_PATH` source changes.
- The view/query SQL, dedup logic, season filters — untouched.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Centralize data-path resolution into paths module`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `paths.py`

```python
import os


def resolve_base_data_path():
    """Resolve the base data directory used by the pipeline.

    Precedence:
      1. BIGDATABALL_DATA_DIR environment variable (tests and custom local runs).
      2. The Google Drive mount on the developer's machine.
      3. A local Data/ folder under the repository root (fallback).
    """
    override = os.environ.get("BIGDATABALL_DATA_DIR")
    if override:
        return override
    if os.path.exists(r"G:\My Drive"):
        return r"G:\My Drive\Documents\bigdataball"
    project_root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(project_root, "Data")
```

`paths.py` lives at the repo root, so `project_root` equals each script's directory —
the fallback is unchanged from the inline versions.

**Verify**:
- `python3 -c "import paths; print(paths.resolve_base_data_path())"` → prints a path
  ending in `/Data` (no `G:` mount, no env var here).
- `BIGDATABALL_DATA_DIR=/tmp/x python3 -c "import paths; print(paths.resolve_base_data_path())"` → `/tmp/x`.

### Step 2: Replace the block in each script

In each of the eight files, replace the path-resolution block with:
```python
import paths
...
BASE_DATA_PATH = paths.resolve_base_data_path()
```
Put `import paths` with the other imports at the top of the file. Keep
`PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))` only if it is used elsewhere
in that file; if `PROJECT_ROOT` is used **only** inside the removed block, delete it too.
For the three export scripts the block is inside a function — set
`BASE_DATA_PATH = paths.resolve_base_data_path()` at the same place inside that function
(do not hoist it to module level there).

Do this one file at a time and run `python3 -m py_compile <file>` after each.

**Verify** (after all eight):
- `python3 -m py_compile *.py` → exit 0.
- `grep -rn 'os.path.exists(r"G:\\My Drive")' *.py` → matches only in `paths.py`
  (one occurrence). No script still contains the inline `G:\My Drive` check.
- For a script-level one: `BIGDATABALL_DATA_DIR=/tmp/x python3 -c "import daily_player_upload as m; print(m.BASE_DATA_PATH)"` → `/tmp/x`.

### Step 3: Add a unit test for `paths.py`

Create `tests/test_paths.py`:
```python
import importlib


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", "/tmp/bdb_override")
    import paths
    importlib.reload(paths)
    assert paths.resolve_base_data_path() == "/tmp/bdb_override"


def test_fallback_to_local_data(monkeypatch):
    monkeypatch.delenv("BIGDATABALL_DATA_DIR", raising=False)
    import paths
    importlib.reload(paths)
    result = paths.resolve_base_data_path()
    # On a machine without the G: mount, this is <repo>/Data.
    assert result.endswith("Data")
```

**Verify**: `python3 -m pytest -q tests/test_paths.py` → passes.

### Step 4: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass (plans 002–004 tests still green,
proving the upload scripts and orchestrator still redirect correctly via `paths.py`).

## Test plan

- New `tests/test_paths.py` covers env-override precedence and the local fallback.
- Existing tests (002–004) act as integration coverage: they reload the upload scripts
  with `BIGDATABALL_DATA_DIR` set and must still resolve to the temp dir — proving the
  refactor preserved the reload semantics.
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `paths.py` exists with `resolve_base_data_path()`.
- [ ] `grep -rn 'G:\\My Drive' *.py` returns matches only in `paths.py`.
- [ ] `python3 -m py_compile *.py` exits 0.
- [ ] `python3 -m pytest -q` exits 0; all prior tests plus `tests/test_paths.py` pass.
- [ ] `git status` shows only the in-scope files changed/created.
- [ ] `plans/README.md` status row for 005 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- Any script uses `PROJECT_ROOT` outside the path block in a way that breaks when you
  remove it — keep `PROJECT_ROOT` in that file instead and report.
- A reloaded upload-script test (002–004) fails after the refactor — the reload no
  longer recomputes `BASE_DATA_PATH`; do not paper over it, report the failure.
- You find a ninth file with the same block not listed here — report it; don't expand
  scope silently.

## Maintenance notes

- A reviewer should confirm every script now sources `BASE_DATA_PATH` from
  `paths.resolve_base_data_path()` and that derived paths are unchanged.
- Follow-up (deferred): reconcile `config.py`'s `BASE_DOWNLOAD_DIR` (used by
  `drive_ingestion.py`) with `paths.py` so Drive ingestion can also honor
  `BIGDATABALL_DATA_DIR`; intentionally out of scope here because Drive download targets
  have different semantics and no local fallback today.
