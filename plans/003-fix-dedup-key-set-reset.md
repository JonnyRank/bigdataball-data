# Plan 003: Stop re-inserting duplicate logs when multiple files are processed in one run

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- daily_player_upload.py daily_fantasy_log_upload.py`
> Note: plan 002 intentionally modifies the path block at the top of both files. The
> dedup loop this plan changes is further down and should be unchanged. Compare the
> "Current state" excerpts against the live code before proceeding; on a mismatch in
> the *loop* code, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: 002 (provides the `player_upload` test fixture and harness)
- **Category**: bug
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

Both upload scripts de-duplicate game logs using an in-memory set `existing_log_keys`.
The intent (stated in the code's own comment) is that after inserting a file's new
logs, their keys are added to this set so the **next** file in the same run doesn't
re-insert them. But `existing_log_keys` is rebuilt **inside** the per-file loop from a
DB snapshot taken once at startup — so the `.update()` from the previous iteration is
wiped at the top of every iteration. When two or more cumulative `.xlsx` files are
processed in a single run (which happens whenever the pipeline runs after missing a
day, leaving several season files in the input folder), logs inserted from the first
file get re-inserted from the second. The result is **duplicate rows** in `player_logs`
/ `fantasy_logs`, which inflate games-played counts and corrupt every downstream
average (`fantasy_averages`, all slate views and CSVs).

## Current state

### `daily_player_upload.py`

The loop starts at line ~105. The key set is rebuilt inside it:

- Snapshot taken once **before** the loop (lines ~68-92): `existing_logs_df` with a
  `log_key` column. This is never updated inside the loop.
- Inside the loop, line ~190:
```python
            existing_log_keys = set(existing_logs_df["log_key"])
```
- After insert, line ~232-241 (the comment reveals the intended behavior):
```python
                # --- Crucial Update ---
                # After adding new logs to the DB, we must also add their keys
                # to our in-memory set to prevent them from being added again
                # when processing the next (cumulative) file in the same run.
                newly_added_keys = set(
                    truly_new_logs_df["PLAYER_ID"].astype(str)
                    + "_"
                    + truly_new_logs_df["DATE"]
                )
                existing_log_keys.update(newly_added_keys)
```
Because line ~190 runs at the top of every iteration, `existing_log_keys` is reset and
the `.update()` is lost.

### `daily_fantasy_log_upload.py`

Identical pattern. The loop starts at line ~150:
- Inside the loop, line ~223:
```python
            existing_log_keys = set(existing_logs_df["log_key"])
```
- After insert, line ~269-274:
```python
                newly_added_keys = set(
                    truly_new_logs_df["PLAYER_ID"].astype(str)
                    + "_"
                    + truly_new_logs_df["DATE"]
                )
                existing_log_keys.update(newly_added_keys)
```

### The fix

Initialize `existing_log_keys` **once, before the loop**, so `.update()` accumulates
across files. In both files, move the `existing_log_keys = set(existing_logs_df["log_key"])`
line out of the loop to just before `for file_path in files_to_process:`, and delete the
in-loop assignment.

## Commands you will need

| Purpose      | Command                                                        | Expected on success      |
|--------------|----------------------------------------------------------------|--------------------------|
| Syntax check | `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` | exit 0 |
| Run tests    | `python3 -m pytest -q`                                          | all pass                 |
| Run one test | `python3 -m pytest -q tests/test_daily_player_upload.py -k dedup_across_files` | passes |

## Scope

**In scope** (the only files you should modify):
- `daily_player_upload.py` — move the `existing_log_keys` init out of the loop.
- `daily_fantasy_log_upload.py` — same change.
- `tests/test_daily_player_upload.py` — add the regression test (Step 3).

**Out of scope** (do NOT touch):
- The dedup *logic* otherwise (the `.isin`, `truly_new_logs_df`, `to_sql` calls stay).
- `existing_logs_df` construction and the DB snapshot — leave as is.
- `daily_fantasy_log_upload.py`'s `unmatched_dk_players` handling — plan 004 owns it.
- The path block at the top — plan 002 owns it.

## Git workflow

- Branch: current branch unless instructed otherwise.
- One commit; message e.g. `Fix duplicate log inserts across files in a single run`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Fix `daily_player_upload.py`

Locate, just above `for file_path in files_to_process:` (after the
`print(f"Found {len(files_to_process)} new file(s) to process...")` line, ~101), and
add:
```python
    # Initialize ONCE before the loop so keys added per file accumulate across files
    # processed in the same run (prevents re-inserting logs from an earlier file).
    existing_log_keys = set(existing_logs_df["log_key"])
```
Then **delete** the in-loop assignment (currently line ~190):
```python
            existing_log_keys = set(existing_logs_df["log_key"])
```
Leave the `existing_log_keys.update(newly_added_keys)` line untouched.

**Verify**: `python3 -m py_compile daily_player_upload.py` → exit 0.
`grep -n "existing_log_keys = set" daily_player_upload.py` → exactly **one** match,
and it is **before** the `for file_path` line (check the line numbers).

### Step 2: Fix `daily_fantasy_log_upload.py`

Apply the identical change: add the init line just above `for file_path in files_to_process:`
(after the `print(f"Found {len(files_to_process)} new file(s) to process...")` at ~146),
and delete the in-loop assignment at ~223.

**Verify**: `python3 -m py_compile daily_fantasy_log_upload.py` → exit 0.
`grep -n "existing_log_keys = set" daily_fantasy_log_upload.py` → exactly **one** match,
before the `for file_path` line.

### Step 3: Add the regression test

Append to `tests/test_daily_player_upload.py` (reuses the `player_upload` fixture and
helpers from plan 002):

```python
def test_dedup_across_files_in_one_run(player_upload):
    """Two cumulative files in the input folder must not produce duplicate logs.
    Regression test for the existing_log_keys reset bug."""
    mod = player_upload
    file1_rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    # file2 is a cumulative file: it repeats file1's logs and adds one new game.
    file2_rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
        (1, "Alpha Player", "2025-11-03", 28),
    ])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_01.xlsx"), file1_rows)
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_02.xlsx"), file2_rows)

    mod.main()  # processes both files in one run (sorted: feed_01 then feed_02)

    # Exactly 3 distinct game logs — the two from file1 must NOT be re-inserted from file2.
    assert _count(mod.engine, "player_logs") == 3
```

**Verify**: `python3 -m pytest -q tests/test_daily_player_upload.py -k dedup_across_files`
→ passes. (Sanity: if you temporarily revert Step 1, this test should fail with
`player_logs == 5`. Re-apply the fix before finishing.)

### Step 4: Full suite

**Verify**: `python3 -m pytest -q` → all tests pass (the 3 from plan 002 plus this one).

## Test plan

- New test `test_dedup_across_files_in_one_run` in `tests/test_daily_player_upload.py`
  covers the exact bug: two cumulative files in one run produce no duplicate logs.
- Patterned after the existing tests in that file (same `player_upload` fixture,
  `write_player_xlsx`, `_count`).
- The player-upload fix and the fantasy-upload fix share the identical code shape;
  the test on the player path is the regression guard for both (the fantasy loop is
  changed identically and verified by `py_compile` + the `grep` single-match check).
- Verification: `python3 -m pytest -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `grep -n "existing_log_keys = set" daily_player_upload.py` → exactly 1 match, before `for file_path`.
- [ ] `grep -n "existing_log_keys = set" daily_fantasy_log_upload.py` → exactly 1 match, before `for file_path`.
- [ ] `python3 -m py_compile daily_player_upload.py daily_fantasy_log_upload.py` exits 0.
- [ ] `python3 -m pytest -q` exits 0; `test_dedup_across_files_in_one_run` is present and passes.
- [ ] `git status` shows only the in-scope files changed.
- [ ] `plans/README.md` status row for 003 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows the dedup loop (not just the path block) already changed since
  `5576703`.
- After moving the init line, `existing_log_keys.update(...)` no longer references the
  same variable name (the update block was refactored away) — report what you find.
- The regression test still reports `player_logs == 5` after your fix (the fix didn't
  take, or the root cause differs from "Current state").

## Maintenance notes

- A reviewer should confirm `existing_log_keys` is initialized exactly once per
  `main()` call, before the loop, and that `existing_logs_df` is still the source of
  the initial keys.
- This bug only manifests with ≥2 files in the input folder in one run; the regression
  test makes that scenario explicit so it can't silently regress.
- If a future change starts re-reading `existing_logs_df` inside the loop, the same
  class of bug could return — keep the single-initialization invariant.
