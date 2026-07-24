# Plan 018: Add a Ruff lint + format gate to CI so style/quality can't silently drift on PRs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat aef8efa..HEAD -- pyproject.toml requirements-dev.txt .github/workflows/test.yml`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live files before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S–M (M only if the linter surfaces many pre-existing violations)
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `aef8efa`, 2026-07-24
- **Issue**: https://github.com/JonnyRank/bigdataball-data/issues/58

## Why this matters

The repo is formatted and linted with **Ruff via the VS Code extension only**
(`docs/codebase/STACK.md` "Linting / Formatting"): there is no committed
`[tool.ruff]` config, Ruff is not a declared dev dependency, and CI
(`.github/workflows/test.yml`) runs `pytest` only. So the linting is invisible
to CI and to any contributor without the extension — a PR that introduces unused
imports, undefined names, or reformatted code passes CI unnoticed, and the
"consistent double-quoting / Black-compatible layout" the docs describe is
enforced by nothing durable. Pinning Ruff as a dev dep, committing a minimal
config, and adding a CI gate makes the existing (already-followed) convention
machine-checked on every push and PR — a standard, low-risk DX hardening.

## Current state

- `requirements-dev.txt` (entire file):

```text
pytest>=7.4
```

- `pyproject.toml` (entire file — no `[tool.ruff]` section):

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

- `.github/workflows/test.yml` — the only workflow that runs on every push/PR
  for tests; its job installs deps and runs pytest (Python 3.13, ubuntu):

```yaml
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
          pip install -e .

      - name: Run tests
        run: python -m pytest -q
```

- Source lives under `src/bigdataball/`; tests under `tests/`. Both should be
  linted. STACK.md states the code already reflects "the Ruff formatter
  defaults," so `ruff format --check` is *expected* to pass on the current tree
  — Step 1 verifies whether that's actually true before wiring the gate.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install Ruff | `pip install ruff` | exit 0 |
| Discover format state | `ruff format --check .` | exit 0 = already formatted (see Step 1) |
| Discover lint state | `ruff check .` | exit 0 = clean (see Step 1) |
| Full test suite (unchanged) | `python -m pytest -q` | `68 passed` |

## Scope

**In scope** (the only files you should modify/create):
- `requirements-dev.txt` (add a pinned `ruff`)
- `pyproject.toml` (add a minimal `[tool.ruff]` section)
- `.github/workflows/test.yml` (add a lint step)
- `plans/README.md` (status row update)
- Source files under `src/bigdataball/` or `tests/` **only if** Step 1 shows
  trivially-safe violations you fix per Step 3 — and only those files.

**Out of scope** (do NOT touch):
- Any behavioral change to source code. Lint fixes are limited to
  import ordering, unused imports, whitespace, and formatting — never logic,
  SQL strings, or control flow. If a lint rule would require a logic change,
  suppress the rule (Step 3b) instead of changing behavior.
- The other workflow files (`claude*.yml`) — the lint gate goes in `test.yml`.

## Git workflow

- Branch: `advisor/018-ci-lint-format-gate` (or the repo's convention from
  `git log --oneline`).
- Commit message style: match `git log` (e.g. "Add a Ruff lint/format gate to
  CI").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Discover the actual lint/format state (decides the rest of the plan)

Install Ruff and run both checks against the current tree, capturing exit codes.
**Discover with the exact ruleset the CI gate will use** (`E,F,W,I` — the same
`select` you configure in Step 2), not Ruff's defaults: Ruff's default set is
`E,F` only, so a bare `ruff check .` here could report clean while the configured
gate later fails on a `W` or `I` (import-order) violation — which would skip
Step 3 and make CI red immediately after the plan lands. Passing `--select`
explicitly makes Step 1's discovery match the gate:

```console
pip install ruff
ruff format --check . ; echo "format_exit=$?"
ruff check --select E,F,W,I . ; echo "lint_exit=$?"
```

Record both exit codes and the violation output. This branches the plan:

- **format_exit=0 and lint_exit=0** → the tree is already clean. Skip Step 3
  entirely; go straight to Step 2 then Step 4.
- **format_exit≠0** → `ruff format` would reformat files. Run `ruff format .`
  (no `--check`) to apply formatting, then `git diff --stat` to see what
  changed. If the diff is pure whitespace/quote/wrap changes across the existing
  files, that is acceptable (it's the formatter the repo already claims to use).
  If the diff touches string *contents* or would change any SQL literal, treat
  it as a STOP condition.
- **lint_exit≠0** → go to Step 3 to triage the specific violations.

**Verify**: you have written down `format_exit`, `lint_exit`, and (if nonzero)
the exact rule codes reported (e.g. `F401`, `E402`). Do not proceed without
this.

### Step 2: Pin Ruff, add a minimal config, wire the CI gate

1. Append a pinned Ruff to `requirements-dev.txt`. Pin an exact version so CI is
   reproducible; use the version you installed in Step 1 (find it with
   `ruff --version`), e.g.:

```text
pytest>=7.4
ruff==<the version from `ruff --version`>
```

2. Add a minimal `[tool.ruff]` section to `pyproject.toml` (after the existing
   `[tool.setuptools.packages.find]` block). Keep it conservative — the default
   rule set (`E`/`F`/`W`) plus import sorting (`I`), matching the observed
   style:

```toml
[tool.ruff]
target-version = "py311"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
```

   (`line-length = 88` matches the Black-compatible layout STACK.md describes.
   If Step 1's `ruff format --check` passed at the default 88, keep it; if the
   repo clearly uses a different width, set it to match and note that.)

3. Add a lint step to `.github/workflows/test.yml`, immediately **before** the
   "Run tests" step (so a lint failure is reported alongside test results). Ruff
   is installed via `requirements-dev.txt`, which the existing "Install
   dependencies" step already installs — no extra install line is needed:

```yaml
      - name: Lint (Ruff)
        run: |
          ruff check .
          ruff format --check .

      - name: Run tests
        run: python -m pytest -q
```

**Verify**:
- `grep -n "^ruff==" requirements-dev.txt` → returns the pinned line.
- `grep -n "tool.ruff" pyproject.toml` → returns the config section.
- `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/test.yml')); print('yaml ok')"` → prints `yaml ok` (if `pyyaml` isn't available, instead run `python -c "import ast; print('skip')"` and visually confirm the indentation matches the surrounding steps).

### Step 3: (Only if Step 1 found lint violations) Triage them conservatively

For each violation from `ruff check .`:

**3a — trivially safe auto-fixes.** Run `ruff check --fix .` which applies only
Ruff's fixes marked safe (unused-import removal, import sorting). Then re-run
`ruff check .` and inspect `git diff`. Accept the diff **only if** every hunk is
an import reorder or an unused-import/whitespace removal. If any fix removes an
import that is actually used at runtime via a side effect (e.g. a module
imported for its import-time registration), revert that specific fix and
suppress the rule instead (3b).

**3b — anything not trivially safe.** Do NOT change code logic to satisfy a
rule. Instead, suppress that specific rule narrowly in `pyproject.toml`, with a
comment explaining why, e.g.:

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "I"]
# E402 (module-level import not at top): config.py calls load_dotenv() before
# importing modules that read env at import time — intentional, don't reorder.
ignore = ["E402"]
```

Only add ignores that are actually needed by the reported violations. If the
number of distinct violations is large (more than a handful of rule codes) or
any requires touching pipeline logic, STOP and report — a human should decide
the ruleset rather than the executor bulk-suppressing.

**Verify**: after 3a/3b, `ruff check . ; echo $?` → `0` and
`ruff format --check . ; echo $?` → `0`.

### Step 4: Confirm the suite still passes and the gate is green locally

**Verify**:
- `python -m pytest -q` → `68 passed` (lint changes must not alter behavior; if
  the count changed, a "trivial" fix wasn't trivial — revert it).
- `ruff check . && ruff format --check . ; echo "gate_exit=$?"` → `gate_exit=0`.

### Step 5: Update the plans index

`plans/README.md`'s "Execution order & status" table already has a `TODO` row
for plan 018 — **update that existing row in place** to DONE (do NOT add a second
018 row), noting whether any pre-existing violations had to be fixed or
suppressed (so the reviewer knows what to look at).

## Test plan

- No new pytest tests (this plan adds tooling, not code paths). The CI lint step
  *is* the new gate; verify it locally with the Step 4 commands.
- The full existing suite (`68 passed`) is the regression guard that any lint
  fix left behavior unchanged.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "^ruff==" requirements-dev.txt` returns a pinned version
- [ ] `grep -n "\[tool.ruff\]" pyproject.toml` returns the config section
- [ ] `.github/workflows/test.yml` has a "Lint (Ruff)" step running `ruff check .` and `ruff format --check .` before the test step
- [ ] `ruff check . && ruff format --check . ; echo $?` → `0`
- [ ] `python -m pytest -q` → `68 passed`
- [ ] Only in-scope files changed (`git status --short`); any source edits are import/whitespace-only (confirm via `git diff`)
- [ ] `plans/README.md` status row for 018 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `ruff format .` (Step 1) would change the *contents* of any string literal or
  SQL statement — formatting must be whitespace/layout only.
- `ruff check .` reports more than a handful of distinct rule codes, or any
  violation whose only fix is a logic change — the ruleset scope is then a human
  decision, not the executor's.
- Any lint "fix" changes the `68 passed` test count.
- The target files don't match the "Current state" excerpts (drift).

## Maintenance notes

- Keep the ruleset small on purpose. Expanding `select` (e.g. adding `B`, `UP`,
  `SIM`) is a separate, opt-in decision — do it in its own PR so the churn is
  reviewable, not bundled with wiring the gate.
- The Ruff version is pinned for reproducibility; a Dependabot/maintenance bump
  should be reviewed because a new Ruff can introduce new default diagnostics.
- STACK.md says the code already follows Ruff defaults — if Step 1 contradicts
  that (large format diff), update STACK.md's "Linting / Formatting" note to
  match the reality this plan establishes.
