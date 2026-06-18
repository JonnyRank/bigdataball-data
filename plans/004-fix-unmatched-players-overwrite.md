# Plan 004: Preserve the regular-season unmatched-players worklist (stop the playoffs stage from clobbering it)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8bf4ce0..HEAD -- daily_fantasy_log_upload.py`
> Plans 002 and 003 have already been applied. This plan only changes the playoffs
> slate block (lines ~320-330 as of 8bf4ce0). Compare the "Current state" excerpt
> against the live code; on a mismatch in that block, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 002 (test harness). Recommended after 003 (same file), but independent.
- **Category**: bug
- **Planned at**: commit `8bf4ce0`, 2026-06-18 (refreshed; original `5576703` 2026-06-16)

## Why this matters

In `daily_fantasy_log_upload.py`, the regular-season slate pipeline returns the list of
DraftKings players that couldn't be matched to the database — this list drives both the
warning email and `todo_mappings.txt`, which is the worklist of player-name mappings the
maintainer still needs to add. Immediately after, the playoffs slate stage **resets the
variable to `[]` and overwrites it** with the playoffs pipeline's result. So the
regular-season worklist is discarded, and during the regular season the email/worklist
instead reflect the playoffs view — which is empty or stale, producing noise and hiding
the real unmatched players.

**Decided behavior (do not change):** the email warning and `todo_mappings.txt` track the
**regular-season** slate only. The playoffs view is still rebuilt every run, but its
unmatched-player result is intentionally **not** used for the worklist.

## Current state (refreshed at 8bf4ce0, 2026-06-18)

Plans 002 and 003 have been applied. The original bug (a `= []` reset followed by
overwriting `unmatched_dk_players` with the playoffs return value) was partially fixed
in commit `f6d787f`: the `= []` reset is gone, and the playoffs block now uses `+=`
to *append* playoffs results to the regular-season list. The worklist is no longer
purely the playoffs results, but it still includes them — violating the "regular-season
only" intent.

`daily_fantasy_log_upload.py`, the slate-pipeline section (lines ~307-330 as of HEAD):

```python
    # --- Run the slate averages pipeline ---
    print("\nStarting slate view update...")
    unmatched_dk_players = []
    try:
        unmatched_dk_players = (
            export_slate_averages_vw.run_slate_averages_pipeline() or []
        )
        print("Slate view update complete.")
    except Exception as e:
        error_msg = f"ERROR in Slate View Update: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

    # --- Run the playoffs slate averages pipeline ---
    print("\nStarting slate view update...")          # <-- still says regular-season
    try:
        unmatched_dk_players += (                    # <-- this is the remaining bug
            export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline() or []
        )
        print("Playoffs slate view update complete.")
    except Exception as e:
        error_msg = f"ERROR in Playoffs Slate View Update: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
```

The remaining fix is **two lines**: replace `unmatched_dk_players += (...)` with a bare
call (discarding the return value), and fix the duplicate `print` message. Downstream code
(lines ~362-384) that writes to `todo_mappings.txt` and the email body does not change.

`run_slate_averages_pipeline()` returns a list of strings; `run_playoffs_slate_averages_pipeline()`
also returns a list. The orchestrator imports both modules at the top
(`import export_slate_averages_vw`, `import export_playoffs_slate_averages_vw`).

`tests/test_orchestrator_warnings.py` does **not** yet exist — the regression test was
not written as part of the partial fix.

## The fix

The regular-season block is correct as-is. In the **playoffs** block: replace the
`unmatched_dk_players +=` line with a bare call that discards the return value, and fix
the duplicate `print` message (it still says "Starting slate view update..." — it should
say "playoffs").

Target shape for the playoffs block (two lines change from the current state):
```python
    # --- Run the playoffs slate averages pipeline ---
    # The playoffs view is still rebuilt every run, but its unmatched-player result is
    # intentionally NOT used for the email warning / todo_mappings worklist — that
    # worklist tracks the regular-season slate. (During the regular season the playoffs
    # view is empty/stale and would flood the worklist with false positives.)
    print("\nStarting playoffs slate view update...")
    try:
        export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline()
        print("Playoffs slate view update complete.")
    except Exception as e:
        error_msg = f"ERROR in Playoffs Slate View Update: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
```

## Commands you will need

| Purpose      | Command                                              | Expected on success |
|--------------|------------------------------------------------------|---------------------|
| Syntax check | `python3 -m py_compile daily_fantasy_log_upload.py`  | exit 0              |
| Run tests    | `python3 -m pytest -q`                               | all pass            |
| Run one test | `python3 -m pytest -q -k unmatched_uses_regular`     | passes              |

## Scope

**In scope** (the only files you should modify):
- `daily_fantasy_log_upload.py` — the playoffs slate block only.
- `tests/test_orchestrator_warnings.py` (create) — the regression test.

**Out of scope** (do NOT touch):
- The regular-season slate block — leave it exactly as is.
- The dedup loop (plan 003) and the path block (plan 002).
- `export_playoffs_slate_averages_vw.py` itself — the playoffs pipeline must still run;
  only the orchestrator's use of its *return value* changes.
- The `todo_mappings.txt` writing and email-body code — its logic is correct once
  `unmatched_dk_players` holds the right list; do not restructure it.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Keep regular-season unmatched players for the warning worklist`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Edit the playoffs slate block

In the playoffs block (the second `try:` block, currently containing `unmatched_dk_players +=`):

1. Change `print("\nStarting slate view update...")` to `print("\nStarting playoffs slate view update...")`.
2. Replace `unmatched_dk_players += (export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline() or [])` with a bare call `export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline()`.

The resulting block must match the "Target shape" above. Do not modify the regular-season block.

**Verify**:
- `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.
- `grep -c "unmatched_dk_players = \[\]" daily_fantasy_log_upload.py` → `1`
  (only the regular-season initializer remains).
- `grep -c "unmatched_dk_players" daily_fantasy_log_upload.py` → matches in the
  regular-season block only; no match inside the playoffs `try:` block.
- `grep -c "Starting slate view update" daily_fantasy_log_upload.py` → `1`
  (the playoffs print now says "playoffs"; the duplicate message is fixed).

### Step 2: Write the regression test

Create `tests/test_orchestrator_warnings.py`. It runs `daily_fantasy_log_upload.main()`
with all heavy stages monkeypatched (so no Google Drive, email, or DB content is needed
beyond a temp dir), the two slate pipelines stubbed to return distinguishable lists, and
asserts the worklist reflects the **regular-season** list only.

```python
import importlib
import os
import sys

import pytest


# Pipeline modules with import-time state (BASE_DATA_PATH / engine / os.makedirs).
# The orchestrator imports all of these at load time, so they must be dropped from the
# module cache before the orchestrator import (so they re-initialize against THIS test's
# temp dir) and again afterward (so a later test never reuses a module bound to this
# now-deleted tmp_path).
_STATEFUL_MODULES = [
    "daily_fantasy_log_upload",
    "daily_player_upload",
    "create_summary_tables",
    "export_slate_averages_vw",
    "export_playoffs_slate_averages_vw",
    "export_slate_averages_csv",
    "drive_ingestion",
]


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Fantasy_Logs").mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))
    # Drop cached pipeline modules so they re-init against this temp dir on import.
    # (pop + import_module yields a fresh import that reads the env var; do not also
    # call importlib.reload — it would re-run module-level code a second time.)
    for name in _STATEFUL_MODULES:
        sys.modules.pop(name, None)
    mod = importlib.import_module("daily_fantasy_log_upload")
    yield mod
    # Clean up so no later test reuses a module bound to this (deleted) tmp_path.
    for name in _STATEFUL_MODULES:
        sys.modules.pop(name, None)


def test_unmatched_uses_regular_season_not_playoffs(orchestrator, monkeypatch):
    mod = orchestrator
    sent = {}

    # Stub the heavy / external stages so main() runs offline against the temp DB.
    monkeypatch.setattr(mod.drive_ingestion, "main", lambda: None)
    monkeypatch.setattr(mod.daily_player_upload, "main", lambda: (0, 0))
    monkeypatch.setattr(mod.create_summary_tables, "run_summary_pipeline", lambda: None)
    monkeypatch.setattr(mod.export_slate_averages_csv, "run_slate_averages_smart_export", lambda: None)
    monkeypatch.setattr(
        mod.export_slate_averages_vw, "run_slate_averages_pipeline",
        lambda: ["RegOnly Player (Best match: X, Score: 50)"],
    )
    monkeypatch.setattr(
        mod.export_playoffs_slate_averages_vw, "run_playoffs_slate_averages_pipeline",
        lambda: ["PlayoffOnly Player (Best match: Y, Score: 50)"],
    )

    def fake_send(subject, body):
        sent["subject"] = subject
        sent["body"] = body

    monkeypatch.setattr(mod.email_notifier, "send_email_alert", fake_send)

    mod.main()

    # The success email's warning section must reflect the regular-season list only.
    assert "RegOnly Player" in sent["body"]
    assert "PlayoffOnly Player" not in sent["body"]

    # todo_mappings.txt must contain the regular-season name, not the playoffs one.
    todo_path = os.path.join(mod.BASE_DATA_PATH, "todo_mappings.txt")
    assert os.path.exists(todo_path)
    with open(todo_path) as f:
        todo = f.read()
    assert "RegOnly Player" in todo
    assert "PlayoffOnly Player" not in todo
```

**Verify**: `python3 -m pytest -q -k unmatched_uses_regular` → passes. (Sanity: if you
temporarily revert Step 1, this test fails because the body/worklist would contain
`PlayoffOnly Player`. Re-apply the fix before finishing.)

### Step 3: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass.

## Test plan

- New test `test_unmatched_uses_regular_season_not_playoffs` in
  `tests/test_orchestrator_warnings.py` asserts that after `main()`, both the email body
  and `todo_mappings.txt` contain the regular-season unmatched name and not the playoffs
  one.
- Uses the same env-var-redirect + reload fixture pattern as plan 002, plus
  `monkeypatch.setattr` to stub the external/heavy stages.
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `grep -c "unmatched_dk_players = \[\]" daily_fantasy_log_upload.py` → `1`.
- [ ] The playoffs block calls `run_playoffs_slate_averages_pipeline()` without assigning
      its result to `unmatched_dk_players`.
- [ ] `python3 -m py_compile daily_fantasy_log_upload.py` exits 0.
- [ ] `python3 -m pytest -q` exits 0; the new test is present and passes.
- [ ] `git status` shows only the in-scope files changed.
- [ ] `plans/README.md` status row for 004 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows the slate-pipeline section already restructured since `8bf4ce0`.
- `main()` in the test raises before reaching the warning code (e.g. a stage you didn't
  stub does real I/O) — report which stage; you may need to stub it too, but do not
  change `main()`'s control flow to make the test pass.
- The pipeline reaches the *error* email branch (`pipeline_errors` non-empty) instead of
  the success branch — that means a stubbed stage still failed; report the error message.

## Maintenance notes

- A reviewer should confirm the playoffs view is still rebuilt (the pipeline is still
  called) and only its return value is discarded.
- If a future change makes the playoffs worklist meaningful (e.g. a separate playoffs
  `todo` file), revisit this decision — it was deliberately scoped to regular-season only.
- The duplicated `print("\nStarting slate view update...")` is corrected to mention
  "playoffs" in Step 1; keep the messages distinct so logs are readable.
- **`orchestrator` fixture vs `fantasy_upload`**: the `orchestrator` fixture in
  `tests/test_orchestrator_warnings.py` (Step 2) is a separate fixture from the
  `fantasy_upload` fixture in `tests/conftest.py`. They serve different purposes —
  `fantasy_upload` is a dedup test fixture; `orchestrator` monkeypatches stages to run
  `main()` end-to-end. If import of `daily_fantasy_log_upload` fails (Google auth libraries
  not found), add Google auth stubs to `_STATEFUL_MODULES` using the same pattern as
  `conftest.py`'s `_STUB_MODULES`.
