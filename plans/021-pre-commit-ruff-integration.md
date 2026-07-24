# Plan 021: Add a pre-commit Ruff hook (local fast-feedback) with cloud session auto-enroll

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 91fa6a0..HEAD -- pyproject.toml requirements-dev.txt .claude/hooks/session-start.sh .pre-commit-config.yaml`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live files before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S–M
- **Risk**: LOW
- **Depends on**: **plan 018 (MUST be DONE first)** — this plan reuses the
  `[tool.ruff]` config and the pinned `ruff` version that plan 018 adds. See the
  hard STOP condition in Step 0.
- **Category**: dx
- **Planned at**: commit `91fa6a0`, 2026-07-24
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/64
- **Reconciled 2026-07-24 @ `ba82f6a`**: drift check clean —
  `git diff --stat 91fa6a0..HEAD -- pyproject.toml requirements-dev.txt .claude/hooks/session-start.sh .pre-commit-config.yaml`
  is empty, no `.pre-commit-config.yaml` exists yet, and the hard dependency on
  plan 018 is still unmet (018 remains TODO). Step 0's STOP condition therefore
  still applies — do not start this plan before 018 lands.

## Why this matters

Plan 018 adds a **CI** Ruff gate — the non-bypassable backstop that fails a PR
when `src`/`tests` code isn't lint-clean or formatted. But CI is *late* feedback:
you find out only after pushing, the check goes red, and someone has to push a
fix commit. A **git pre-commit hook** moves that same check to commit time, so
formatting/lint issues are caught (and auto-fixed) *before* they ever reach a PR.

Crucially, a git pre-commit hook fires on **any** `git commit` in a clone where
`pre-commit install` has run — a human at a terminal, a local Claude Code / other
agent session, whoever — because it hooks git itself, not a particular tool. This
plan wires that up **once** and auto-enrolls Claude Code on the web sessions via
the existing remote `SessionStart` hook, so local development, local agent
sessions, and cloud sessions all format on the same rules.

This does **not** replace plan 018's CI gate. Pre-commit is convenience and is
bypassable (`git commit --no-verify`, or simply a clone where nobody ran
`pre-commit install`); CI remains the enforcement. They share a single source of
truth — the `[tool.ruff]` config in `pyproject.toml` — so local and CI never
disagree.

## Current state

- **Plan 018 must already be executed.** After 018, `pyproject.toml` has a
  `[tool.ruff.lint]` section with `select = ["E", "F", "W", "I"]` and
  `requirements-dev.txt` pins an exact `ruff==<version>`. This plan reads that
  version and reuses that config. If they are absent, 018 is not done — STOP
  (Step 0).

- `requirements-dev.txt` after plan 018 looks like (the exact `ruff` version
  will vary — read it, don't assume):

```text
pytest>=7.4
ruff==0.16.0
```

- `.claude/hooks/session-start.sh` — the **remote-only** SessionStart hook that
  bootstraps the `.venv` for Claude Code on the web sessions. The relevant tail
  (verified at plan time; line numbers may shift — match on content):

```bash
# Upgrading pip is a nice-to-have, not a requirement — never fail the session on it.
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip || true
"$VENV_DIR/bin/python" -m pip install --quiet -r requirements.txt -r requirements-dev.txt

# Make the venv the default interpreter for the rest of the session so `python`
# and `pytest` resolve to it in subsequent Bash commands.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export VIRTUAL_ENV=\"$VENV_DIR\"" >> "$CLAUDE_ENV_FILE"
  echo "export PATH=\"$VENV_DIR/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

exit 0
```

  The whole script is guarded by `if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then exit 0; fi`
  near the top, so it is a **no-op on local machines** — cloud only. That guard
  is why the auto-enroll (Step 3) only affects cloud sessions and never touches a
  developer's machine.

- There is **no `.pre-commit-config.yaml`** and **no Makefile** in the repo yet.
  The project's primary human docs are `CLAUDE.md` (Build/Run/Testing) and
  `docs/codebase/INTEGRATIONS.md` ("CI / Automation" documents the SessionStart
  hook). Those are where the local `pre-commit install` step gets documented.

- **Scope must match plan 018's gate**: Ruff runs on `src/` and `tests/` only —
  never Markdown, never the vendored `.claude/skills/.../scan.py`. The
  pre-commit hooks below enforce that with `files: ^(src|tests)/`.

- Repo conventions: double-quoted strings, 4-space indent in shell/py; print-/
  comment-documented scripts; docs are Markdown under `docs/codebase/`. Match
  the surrounding style of each file you edit.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install pre-commit + ruff (dev) | `pip install -r requirements-dev.txt` | exit 0 |
| Wire the git hook locally | `pre-commit install` | prints `pre-commit installed at .git/hooks/pre-commit` |
| Run all hooks over the repo | `pre-commit run --all-files` | all hooks `Passed` (after any auto-fix + re-run) |
| Full test suite (unchanged) | `python -m pytest -q` | same count as before your changes (68 if only 018 precedes 021; more if 019 has landed) |

## Scope

**In scope** (the only files you should create/modify):
- `.pre-commit-config.yaml` (create)
- `requirements-dev.txt` (add a pinned `pre-commit`)
- `.claude/hooks/session-start.sh` (add the cloud auto-enroll line)
- `CLAUDE.md` (document the one-time local `pre-commit install`)
- `docs/codebase/INTEGRATIONS.md` (note the pre-commit hook + cloud auto-enroll)
- `plans/README.md` (status row update)

**Out of scope** (do NOT touch):
- `pyproject.toml`'s `[tool.ruff]` — plan 018 owns it; this plan only *reuses*
  it. Do not change the ruleset, `select`, or `line-length` here.
- `.github/workflows/test.yml` — the CI gate is plan 018's; this plan adds a
  *local* hook, not a CI change.
- Any `src/` or `tests/` source — if `pre-commit run --all-files` reports
  formatting/lint changes on existing code, that means plan 018's own Step 1
  didn't leave the tree clean; STOP and report rather than reformatting source
  here (that is 018's job, not 021's).
- Do NOT add a Makefile — documenting the one command in `CLAUDE.md` is enough;
  a build system is a separate decision (noted under Maintenance).

## Git workflow

- Branch: `advisor/021-pre-commit-ruff` (or the repo's convention from
  `git log --oneline`).
- Commit message style: match `git log` (short imperative subject, e.g.
  "Add a pre-commit Ruff hook with cloud session auto-enroll").
- **Heads-up**: once you create `.pre-commit-config.yaml` and run
  `pre-commit install`, *your own* commits in this worktree will run the hook. If
  a commit aborts with "files were modified by this hook," that is the hook
  fixing formatting — `git add -u` and commit again. This is expected (see Step
  5). Do NOT use `--no-verify` to force past it.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Confirm plan 018 is done (hard gate)

This plan is meaningless without plan 018's `[tool.ruff]` config — without it the
Ruff pre-commit hooks would run against Ruff's **default** rule set (413 rules as
of 0.16.0) instead of the intended `E,F,W,I`.

```console
grep -n '\[tool.ruff.lint\]' pyproject.toml
grep -n 'select = \["E", "F", "W", "I"\]' pyproject.toml
grep -nE '^ruff==' requirements-dev.txt
```

**STOP condition**: if any of these returns nothing, plan 018 has not been
executed/merged. Stop and report "plan 018 must land first" — do not add a
`[tool.ruff]` section yourself (that is 018's scope).

Record the exact ruff version from `requirements-dev.txt` (e.g. `0.16.0`) — you
need it for the hook `rev` in Step 1.

**Verify**: all three greps return a line; you have written down the ruff version.

### Step 1: Create `.pre-commit-config.yaml`

Create `.pre-commit-config.yaml` at the repo root. Pin the `ruff-pre-commit`
`rev` to **`v<the exact ruff version from Step 0>`** so the local hook and CI use
the identical Ruff build (otherwise local and CI can format differently across a
Ruff release). Use this content (replace `v0.16.0` with `v<version from Step 0>`
if different):

```yaml
# Local fast-feedback mirror of the CI Ruff gate (plans 018 + 021).
# - Rules/line-length come from [tool.ruff] in pyproject.toml (single source of
#   truth shared with CI), so local and CI never disagree.
# - Scoped to src/ and tests/ to match the CI gate exactly: never touches
#   Markdown (Ruff 0.16.0 can format python fences in .md — we don't want that
#   here) or the vendored .claude/ scripts.
# - Keep `rev` in lockstep with `ruff==` in requirements-dev.txt.
# One-time local setup:  pip install -r requirements-dev.txt && pre-commit install
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.0
    hooks:
      - id: ruff-check
        args: [--fix]
        files: ^(src|tests)/
      - id: ruff-format
        files: ^(src|tests)/
```

Notes for the executor:
- Hook ids: current `ruff-pre-commit` exposes `ruff-check` (lint) and
  `ruff-format` (format). If the pinned `rev` predates the `ruff-check` alias and
  `pre-commit run` errors with "hook id `ruff-check` not found", use the legacy
  id `ruff` for the lint hook instead, and note it in your report.
- `args: [--fix]` makes the lint hook auto-fix safe issues (import order, unused
  imports). `ruff-format` always rewrites formatting. Both then abort the commit
  so the changes are visible for you to re-stage — that is the intended flow.
- Do NOT add `types_or`/markdown to these hooks. The `files: ^(src|tests)/` scope
  plus Ruff's Python-only defaults keep the hook off `.md` and `.claude/`.

**Verify**: `grep -n 'files: \^(src|tests)/' .pre-commit-config.yaml` returns
**two** lines (one per hook). Do **not** add a `python -c "import yaml; ..."`
check here — PyYAML is not a declared dependency and may be absent in a clean
env; full YAML/schema validity is checked in Step 5 with
`pre-commit validate-config` once `pre-commit` is installed in Step 2.

### Step 2: Add `pre-commit` to the dev dependencies

Append a pinned `pre-commit` to `requirements-dev.txt` so both local `pip install
-r requirements-dev.txt` and the cloud SessionStart install pull it in. Pick the
version you actually install (find it after `pip install pre-commit` with
`pre-commit --version`):

```text
pytest>=7.4
ruff==<existing pin from plan 018 — leave unchanged>
pre-commit==<the version you installed>
```

**Verify**: `grep -nE '^pre-commit==' requirements-dev.txt` returns the pinned
line; the existing `ruff==` line is unchanged (`git diff requirements-dev.txt`
shows only an added `pre-commit==` line).

### Step 3: Auto-enroll cloud sessions in the hook (edit `session-start.sh`)

In `.claude/hooks/session-start.sh`, **immediately after** the
`pip install ... -r requirements.txt -r requirements-dev.txt` line and **before**
the `# Make the venv the default interpreter ...` block, insert:

```bash
# Auto-enroll Claude Code on the web sessions in the git pre-commit hooks (plan
# 021) so commits made from a cloud session run the same Ruff format/lint as CI.
# pre-commit is installed via requirements-dev.txt above. Never fail the session
# on it — the hook is convenience; CI (plan 018) is the enforcement — but DO
# surface a failure so a cloud session isn't silently left without the hook.
if ! "$VENV_DIR/bin/pre-commit" install --install-hooks >/dev/null 2>&1; then
  echo "Warning: pre-commit hook install failed; CI (plan 018) remains the enforcement." >&2
fi
```

The `if ! ...; then ... fi` form stays **non-fatal** — a command in an `if`
condition is exempt from the script's `set -e`, so the session continues to
`exit 0` regardless — while still emitting a warning to stderr instead of the
silent `|| true`. (Do not revert to bare `|| true`: it hides a broken enrollment.)

This runs only in remote sessions (the whole script is already guarded by the
`CLAUDE_CODE_REMOTE` check near the top), so a developer's local machine is never
touched by this line — local users opt in explicitly via Step 4's documented
command. `--install-hooks` also pre-fetches the hook environment so the first
cloud commit isn't slow.

**Verify**: `grep -n 'pre-commit install --install-hooks' .claude/hooks/session-start.sh` returns the inserted line, positioned after the `requirements-dev.txt` install and before the `CLAUDE_ENV_FILE` block (`sed -n` around it to confirm ordering); `grep -n 'Warning: pre-commit hook install failed' .claude/hooks/session-start.sh` returns the warning line (confirms the non-silent form). `bash -n .claude/hooks/session-start.sh` → exits 0 (valid shell syntax). (The runtime effect — `.git/hooks/pre-commit` actually being written — is exercised locally in Step 5; a cloud SessionStart can't be simulated here.)

### Step 4: Document the one-time local setup

Local (non-cloud) developers and agents must run `pre-commit install` once per
clone — the git hook cannot install itself into a clone nobody has touched.

1. In `CLAUDE.md`, under the **"Build And Run"** section, right after the
   `pip install -r requirements.txt` / editable-install lines, add a short note:

   > **Enable the local format/lint hook (once per clone):**
   > `pip install -r requirements-dev.txt && pre-commit install`. This runs Ruff
   > format + lint (`src`/`tests` only) on every `git commit`, matching the CI
   > gate. Claude Code on the web sessions are enrolled automatically by the
   > `SessionStart` hook — this step is for local clones only.

2. In `docs/codebase/INTEGRATIONS.md`, in the **"CI / Automation"** section that
   already describes the SessionStart hook, add one bullet noting that the
   SessionStart hook also runs `pre-commit install` (cloud auto-enroll), and that
   `.pre-commit-config.yaml` mirrors the CI Ruff gate on `src`/`tests` using the
   same `[tool.ruff]` config, `rev` pinned to the `ruff==` version. Include a
   sentence setting the expectation that, because the hooks auto-fix, a **cloud
   session's commit will abort the first time if it reformats staged files** —
   the session then re-stages (`git add -u`) and commits again. This is steady-
   state behavior for every enrolled session, not a one-off, so it shouldn't be
   mistaken for an error.

Keep both edits brief and match the surrounding prose style.

**Verify**: `grep -n 'pre-commit install' CLAUDE.md` returns the new note; `grep -n 'pre-commit' docs/codebase/INTEGRATIONS.md` returns the new bullet.

### Step 5: Prove the hook works (create → fix → clean)

1. Install and wire it: `pip install -r requirements-dev.txt && pre-commit install`
   → prints `pre-commit installed at .git/hooks/pre-commit`. Then confirm the
   config parses and the hook file was written (this is the YAML/schema check
   deferred from Step 1 — it uses `pre-commit`, so no PyYAML dependency):
   `pre-commit validate-config .pre-commit-config.yaml` → exits 0 (no output on
   success), and `test -f .git/hooks/pre-commit && echo "hook installed"` →
   prints `hook installed`.

2. Run it over the whole repo: `pre-commit run --all-files`. On a tree where plan
   018 already left `src`/`tests` clean, both hooks report **`Passed`** (or
   `ruff-format`/`ruff-check` report "Passed" after making no changes). If a hook
   reports files were modified, inspect `git diff` — if the changes are only in
   `src/`/`tests/` and are pure formatting/import-order, that means 018's tree
   wasn't actually clean → **STOP and report** (do not commit source reformatting
   under this plan).

3. Prove it *catches* a violation without committing bad code to the repo:
   create a throwaway badly-formatted file, confirm the hook flags/fixes it, then
   delete it — nothing from this test is committed:

```console
printf 'import os,sys\nx=1\n' > src/bigdataball/_pretest_tmp.py
pre-commit run --files src/bigdataball/_pretest_tmp.py ; echo "hook_exit=$?"
rm -f src/bigdataball/_pretest_tmp.py
```

   Expected: `ruff-format` and/or `ruff-check` report a failure / modification
   (nonzero `hook_exit`), demonstrating the hook is active on `src/`. (The file
   is deleted immediately; do not stage or commit it.)

**Verify**: step 2 leaves `git status` clean (no source changes); the step-3
throwaway is gone (`test ! -e src/bigdataball/_pretest_tmp.py`).

### Step 6: Confirm the suite is unaffected and update the index

`python -m pytest -q` → the **same count as before your changes** (68 on a tree
where only plan 018 precedes 021; higher if plan 019 — a test plan, also `TODO`
with no hard ordering vs 021 — has already landed). This plan adds no code paths,
so the number must be *unchanged by your work*; if it moved, you accidentally
edited source.

Then update `plans/README.md`: the "Execution order & status" table already has a
`TODO` row for plan 021 — **update that existing row in place** to DONE (do NOT
add a second 021 row), and confirm the "Depends on" column shows 018.

## Test plan

- No new pytest tests — pre-commit is a git-level tool, not application code.
  Verification is the Step 5 manual sequence (`pre-commit run --all-files` clean;
  a throwaway bad file is caught then deleted) plus the full suite (count
  unchanged by this plan) as the regression guard that no source was altered.
- If the repo later wants automated coverage of the hook config, a CI job could
  run `pre-commit run --all-files` — but that overlaps plan 018's gate and is
  intentionally **not** added here (see Maintenance).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.pre-commit-config.yaml` exists, pins `ruff-pre-commit` `rev` to `v<ruff version from requirements-dev.txt>`, scopes both hooks with `files: ^(src|tests)/`, and `pre-commit validate-config .pre-commit-config.yaml` exits 0
- [ ] `grep -nE '^pre-commit==' requirements-dev.txt` returns a pinned version; the `ruff==` pin is unchanged
- [ ] `.claude/hooks/session-start.sh` runs `pre-commit install --install-hooks` inside the `CLAUDE_CODE_REMOTE` guard, in the non-fatal warn-don't-fail form (emits a `Warning:` on failure, does not exit non-zero), and `bash -n` on it exits 0
- [ ] `CLAUDE.md` documents the one-time local `pre-commit install`
- [ ] `docs/codebase/INTEGRATIONS.md` mentions the pre-commit hook + cloud auto-enroll (incl. the abort-and-recommit expectation)
- [ ] After `pre-commit install`, `test -f .git/hooks/pre-commit` succeeds
- [ ] `pre-commit run --all-files` passes with **no** changes to `src/`/`tests/` (`git status` clean afterward)
- [ ] `python -m pytest -q` shows the **same count as before your changes** (68 if only 018 precedes 021; unchanged by 021 regardless of whether 019 has landed)
- [ ] `git status --short` shows only the in-scope files (plus `plans/README.md`); no `src/`/`tests/`/`pyproject.toml`/`test.yml` changes
- [ ] `plans/README.md` status row for 021 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 018 is not detectable (Step 0 greps fail) — 018 must land first.
- `pre-commit run --all-files` wants to reformat existing `src/`/`tests/` code —
  that's a sign 018's tree wasn't clean; reformatting source is 018's job, not
  this plan's.
- The `ruff-check` hook id isn't found for the pinned `rev` and the legacy `ruff`
  id also fails — report the `ruff-pre-commit` version mismatch rather than
  guessing hook ids.
- Adding `pre-commit install` to `session-start.sh` would require removing the
  `CLAUDE_CODE_REMOTE` guard (it must not — cloud-only is deliberate).

## Maintenance notes

- **Two pins must move together.** The `rev:` in `.pre-commit-config.yaml` and
  the `ruff==` in `requirements-dev.txt` must always name the same Ruff version,
  or local and CI can format differently. A Ruff bump touches both, in one PR.
- **Pre-commit is convenience, not enforcement.** It's bypassable
  (`--no-verify`) and absent in clones that never ran `pre-commit install`. Plan
  018's CI gate is the guarantee; keep both. Do not remove the CI gate "because
  pre-commit covers it."
- **Scope parity with CI.** If plan 018's CI gate scope ever changes (e.g. a
  future root-level package added to `ruff check`), update
  `.pre-commit-config.yaml`'s `files:` pattern to match, or the two diverge.
- **A `make setup` target** (running `pip install -r requirements-dev.txt &&
  pre-commit install`) would streamline local onboarding, but the repo has no
  Makefile today; adding a build system is a separate, deliberate decision left
  out of this plan.
- Reviewer should confirm: the hook is scoped to `src`/`tests` (not `.`), the
  `rev` matches the `ruff==` pin, and the `session-start.sh` addition stays
  inside the `CLAUDE_CODE_REMOTE` guard and stays non-fatal (the warn-don't-fail
  `if ! ...; then echo Warning >&2; fi` form, not a silent `|| true`).
