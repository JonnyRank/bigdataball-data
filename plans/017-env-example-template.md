# Plan 017: Commit a `.env.example` template so required environment variables are discoverable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat aef8efa..HEAD -- src/bigdataball/config.py docs/codebase/INTEGRATIONS.md`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code/doc before proceeding; on a mismatch,
> treat it as a STOP condition (the env-var list below may be stale).

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `aef8efa`, 2026-07-24
- **Issue**: —

## Why this matters

The pipeline reads six environment variables from a `.env` file
(`config.py` via `python-dotenv`), but **no `.env.example`/template is
committed** — `docs/codebase/INTEGRATIONS.md` explicitly says so. A person
setting the pipeline up on a new machine (or a contributor) can only discover
the required variable names by reading `config.py` and grepping the codebase.
A committed `.env.example` with the variable **names and placeholder values**
(never real secrets) is the standard, zero-risk fix: it documents the contract
in one obvious file, and `cp .env.example .env` becomes the first setup step.

**Security boundary (hard rule):** this file contains variable **names and
placeholder values only** — never a real token, password, folder ID, or email.
`.env` (the real file) stays git-ignored; `.env.example` is safe to commit
precisely because it holds no secrets.

## Current state

- `src/bigdataball/config.py` reads these env vars (the complete list — verified
  against the file at plan time):

```python
# config.py
DATASET_JOBS = [
    {"drive_folder_id": os.getenv("DRIVE_FOLDER_ID_DFS"), ...},     # line 13
    {"drive_folder_id": os.getenv("DRIVE_FOLDER_ID_PLAYER"), ...},  # line 20
]
EMAIL_SENDER = os.getenv("EMAIL_SENDER")       # line 33
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")   # line 34
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")   # line 35
```

- One more variable is read elsewhere (not in `config.py`) and belongs in the
  template as an **optional** override: `BIGDATABALL_DATA_DIR`, read by
  `paths.resolve_base_data_path()` (`src/bigdataball/paths.py:12`) and by the
  test harness. `docs/codebase/INTEGRATIONS.md` "Environment Variables" table is
  the authoritative list — it enumerates exactly these six.

- `docs/codebase/INTEGRATIONS.md` "Environment Variables (`.env` ...)" section
  currently opens with:
  `No .env.example/.env.template is committed; required vars are read in config.py:`
  followed by a table. This sentence must be updated once the example exists.

- `.gitignore` ignores `.env` (line under "Security: Exclude credentials and
  tokens") but **not** `.env.example` — the pattern is the exact name `.env`, so
  a file named `.env.example` is committed normally. Confirm with the verify
  command in Step 1.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm `.env.example` is not git-ignored | `git check-ignore .env.example; echo "exit=$?"` | prints `exit=1` (i.e. NOT ignored) |
| Confirm real `.env` stays ignored | `git check-ignore .env; echo "exit=$?"` | prints `.env` then `exit=0` (still ignored) |
| Full suite (unchanged) | `python -m pytest -q` | `68 passed` |

## Scope

**In scope** (the only files you should create/modify):
- `.env.example` (create, at repo root)
- `docs/codebase/INTEGRATIONS.md` (update the one "No .env.example ... committed"
  sentence to point at the new file)
- `plans/README.md` (status row update only)

**Out of scope** (do NOT touch):
- `src/bigdataball/config.py` — do not change how vars are read; this plan only
  documents them.
- `.gitignore` — the real `.env` must remain ignored; do not add or loosen any
  rule.
- Any real `.env` file if one happens to exist in the working tree — do NOT
  read its values into the example, and do NOT commit it.

## Git workflow

- Branch: `advisor/017-env-example-template` (or the repo's branch-naming
  convention if one is evident from `git log --oneline`).
- Commit message style: match `git log` (e.g. "Add a .env.example template for
  required environment variables").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm `.env.example` will be committed (not ignored)

**Verify**: `git check-ignore .env.example; echo "exit=$?"` → prints `exit=1`
(a git-ignore *miss* — the file is NOT ignored). If it prints `exit=0`, the
`.gitignore` has a broader rule than expected — treat this as a STOP condition
and report, rather than editing `.gitignore`.

### Step 2: Create `.env.example` at the repo root

Create `.env.example` with placeholder values only. Use exactly this content:

```dotenv
# .env.example — copy to .env and fill in real values (never commit .env).
# The pipeline reads these via python-dotenv in src/bigdataball/config.py.
# See docs/codebase/INTEGRATIONS.md for what each one is used for.

# Google Drive folder IDs (from the Drive URL of each source folder).
DRIVE_FOLDER_ID_DFS=your-dfs-feed-folder-id
DRIVE_FOLDER_ID_PLAYER=your-player-feed-folder-id

# Gmail notification (EMAIL_PASSWORD is a Gmail *app password*, not your login).
EMAIL_SENDER=you@example.com
EMAIL_PASSWORD=your-gmail-app-password
EMAIL_RECEIVER=alerts@example.com

# Optional: override the base data directory (env override wins over the G:
# mount and the local Data/ fallback). Tests set this to a temp dir.
# BIGDATABALL_DATA_DIR=/absolute/path/to/data
```

Every value above is a placeholder. Do NOT substitute any real credential,
folder ID, or address, even if one is visible in the environment.

**Verify**: `test -f .env.example && grep -c "=" .env.example` → prints a number
`>= 5` (the five required vars are present; `BIGDATABALL_DATA_DIR` is commented).
Then: `grep -Eic "AIza|ya29|-----BEGIN|@gmail\.com" .env.example` → prints `0`
(no real-looking secrets or real Gmail addresses leaked in).

### Step 3: Update the INTEGRATIONS doc pointer

In `docs/codebase/INTEGRATIONS.md`, change the sentence that currently reads:

> `No .env.example/.env.template is committed; required vars are read in config.py:`

to:

> `Copy the committed .env.example template to .env and fill in real values; required vars are read in config.py:`

Leave the variable table that follows it unchanged.

**Verify**: `grep -n "committed .env.example template" docs/codebase/INTEGRATIONS.md` → returns the updated line.

### Step 4: Confirm nothing broke and update the index

**Verify**: `python -m pytest -q` → `68 passed` (no code changed, so the suite
is unaffected — this confirms you didn't accidentally edit a source file).

Then update `plans/README.md`: add a DONE status row for plan 017 in the
"Execution order & status" table, matching the existing rows' formatting.

## Test plan

- No new automated tests (this plan adds documentation/config only; there is no
  code path to test).
- Verification is the `git check-ignore` and `grep` commands above plus the
  unchanged full suite.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.env.example` exists at the repo root and contains all five required vars (`DRIVE_FOLDER_ID_DFS`, `DRIVE_FOLDER_ID_PLAYER`, `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVER`)
- [ ] `git check-ignore .env.example; echo $?` reports the file is NOT ignored (exit 1)
- [ ] `git check-ignore .env; echo $?` confirms the real `.env` is still ignored (exit 0)
- [ ] `grep -Eic "AIza|ya29|-----BEGIN" .env.example` → `0` (no real secret material)
- [ ] `docs/codebase/INTEGRATIONS.md` no longer says "No .env.example ... is committed"
- [ ] `python -m pytest -q` → `68 passed`
- [ ] `git status --short` shows only `.env.example`, `docs/codebase/INTEGRATIONS.md`, and `plans/README.md`
- [ ] `plans/README.md` status row for 017 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `git check-ignore .env.example` reports the file IS ignored (exit 0) — do not
  edit `.gitignore` to work around it; report the unexpected rule.
- `config.py`'s env-var reads differ from the "Current state" list (e.g. a new
  variable was added or one renamed) — update the template to match reality and
  note the discrepancy in your report rather than committing a stale list.
- A real `.env` file exists in the working tree — do NOT open it, copy its
  values, or commit it; use only the placeholders above and report that a real
  `.env` is present.

## Maintenance notes

- Whenever a new `os.getenv(...)` is added to `config.py` (or a new
  `BIGDATABALL_*` override elsewhere), add it to `.env.example` in the same PR —
  the template is only useful if it stays complete. A reviewer should check the
  template against `config.py`'s reads on any config change.
- The `docs/codebase/INTEGRATIONS.md` env-var table remains the prose reference;
  the `.env.example` is the copy-paste starting point. Keep them consistent.
