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
- **Reviewed 2026-07-24 (Ruff 0.16.0)**: `review-plan` pass triggered by Ruff
  0.16.0 (released 2026-07-23), which grew the *default* lint rule set from 59 to
  413 rules and made `ruff format` reformat Python code blocks inside Markdown by
  default. Outcome: (1) the lint side is **unaffected** — this plan pins the rule
  set with an explicit `select` (an exact allowlist that overrides Ruff's
  defaults entirely; see "Note on Ruff ≥ 0.16.0" below), so the 59→413 default
  jump changes nothing about which rules run; (2) the **format gate was scoped to
  `src tests`** (was `.`), because `ruff format --check .` would now also
  format-check the ~20 Markdown files in `docs/` and `plans/` that contain
  ```python``` code fences (including these plan files) and fail CI on
  documentation rather than source. The three target files
  (`pyproject.toml`, `requirements-dev.txt`, `.github/workflows/test.yml`) are
  unchanged since `aef8efa`, so the drift check base still holds.
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
- **All first-party Python lives under `src/` and `tests/`** — plan 009 moved
  every module into the `src/bigdataball/` package, so there is no root-level
  `.py`. The only other `.py` anywhere in the tree is a vendored skill helper,
  `.claude/skills/acquire-codebase-knowledge/scripts/scan.py`, which is **not**
  first-party pipeline code and is intentionally left out of the gate. That is
  why every Ruff command below targets `src tests` explicitly rather than `.`
  (see the next section for why `.` is actively wrong here).

## Note on Ruff ≥ 0.16.0 (read before running any command)

Ruff 0.16.0 (2026-07-23) changed two things that matter to this plan. Both are
already accounted for below; this note explains *why* the commands look the way
they do so you don't "simplify" them back.

1. **The default lint rule set grew from 59 to 413 rules.** This does **not**
   affect this plan, because Step 2 configures an explicit
   `select = ["E", "F", "W", "I"]`. In Ruff, `select` is an *exact allowlist*: it
   implicitly disables every rule and then enables only the listed ones —
   `select` **replaces** Ruff's built-in defaults (that is what distinguishes it
   from `extend-select`, which *adds to* the defaults). So the rule set this gate
   enforces is exactly E, F, W, I regardless of how large Ruff's default set
   becomes. Do **not** switch `select` to `extend-select` — that would pull in
   all 413 default rules and flood CI. If you ever run a *bare* `ruff check .`
   (no `--select`) for exploration, expect hundreds of violations from the new
   defaults; that is not this gate.

2. **`ruff format` now reformats Python code blocks inside Markdown by default,**
   and `ruff format .` (or `ruff format --check .`) recurses into `.md` files. This
   repo has ~20 Markdown files with ```python``` fences (all of `plans/`, several
   `docs/codebase/*.md`) whose snippets are hand-written and not Ruff-formatted.
   Running the gate over `.` would therefore fail `ruff format --check` on
   documentation. **Every *gate* command in this plan targets `src tests`** so the
   gate only governs actual source (the bare `ruff check .` / `ruff format .`
   forms appear below only as anti-patterns to avoid, never as gate commands). This is intentional — Markdown code-block
   formatting is explicitly out of scope (see Maintenance notes).

   The `src tests` scoping is the right call **independent of the exact 0.16.0
   formatter detail**: it also keeps the gate off the one vendored non-first-party
   script (`.claude/.../scan.py`) and confines linting/formatting to first-party
   source. So even if the "formats Markdown by default" behavior is ever nuanced
   by a point release, the action here still holds — do not widen the gate to `.`.

3. **Two command forms, both intentional — not an inconsistency.** *Before* Step 2
   writes the `[tool.ruff.lint] select` to `pyproject.toml`, discovery and triage
   pass `--select E,F,W,I` explicitly (Step 1, Step 3 header) so they match the
   gate without relying on config that isn't there yet. *After* Step 2, the bare
   `ruff check src tests` (Step 3 Verify, Step 4, Done criteria, CI YAML) inherits
   that same `select` from `pyproject.toml`. Both run exactly E/F/W/I — the
   explicit flag is only needed pre-config.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install Ruff | `pip install ruff` | exit 0 |
| Discover format state | `ruff format --check src tests` | exit 0 = already formatted (see Step 1) |
| Discover lint state | `ruff check --select E,F,W,I src tests` | exit 0 = clean (see Step 1) |
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

Install Ruff and run both checks against the Python source (`src tests`),
capturing exit codes. Two deliberate choices (see "Note on Ruff ≥ 0.16.0"):

- **Discover with the exact ruleset the CI gate will use** (`--select E,F,W,I`,
  the same `select` you configure in Step 2), not Ruff's defaults. As of Ruff
  0.16.0 the default rule set is huge (413 rules), so a *bare* `ruff check .`
  would report hundreds of violations that this gate does not enforce; and even
  on older Ruff the default omitted `W`/`I`. Either way the bare command does not
  match the gate — passing `--select` explicitly makes discovery match it.
- **Target `src tests`, not `.`** — Ruff 0.16.0's `ruff format` recurses into
  Markdown and would format-check the ```python``` fences in `plans/`/`docs/`,
  failing on documentation. Scope to the Python source.

```console
pip install ruff
ruff format --check src tests ; echo "format_exit=$?"
ruff check --select E,F,W,I src tests ; echo "lint_exit=$?"
```

Record both exit codes and the violation output. This branches the plan:

- **format_exit=0 and lint_exit=0** → the tree is already clean. Skip Step 3
  entirely; go straight to Step 2 then Step 4.
- **format_exit≠0** → `ruff format` would reformat files. Run `ruff format src tests`
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
   `[tool.setuptools.packages.find]` block). Keep it conservative — an explicit,
   small allowlist of pycodestyle errors + Pyflakes + warnings (`E`/`F`/`W`) plus
   import sorting (`I`), matching the observed style. Use `select` (an exact
   allowlist that overrides Ruff's defaults), **not** `extend-select` — see "Note
   on Ruff ≥ 0.16.0": `extend-select` would layer these on top of Ruff's 413
   default rules and flood CI.

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
          ruff check src tests
          ruff format --check src tests

      - name: Run tests
        run: python -m pytest -q
```

(The `src tests` scope is load-bearing, not cosmetic — see "Note on Ruff ≥
0.16.0". `ruff check`/`ruff format --check` over `.` would drag Ruff into the
Markdown under `plans/` and `docs/` and fail the gate on documentation.)

**Verify**:
- `grep -n "^ruff==" requirements-dev.txt` → returns the pinned line.
- `grep -n "tool.ruff" pyproject.toml` → returns the config section.
- `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/test.yml')); print('yaml ok')"` → prints `yaml ok` (if `pyyaml` isn't available, instead run `python -c "import ast; print('skip')"` and visually confirm the indentation matches the surrounding steps).

### Step 3: (Only if Step 1 found lint violations) Triage them conservatively

For each violation from `ruff check --select E,F,W,I src tests`:

**3a — trivially safe auto-fixes.** Run `ruff check --fix src tests` which applies
only Ruff's fixes marked safe (unused-import removal, import sorting). Then re-run
`ruff check src tests` and inspect `git diff`. Accept the diff **only if** every hunk is
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

**Verify**: after 3a/3b, `ruff check src tests ; echo $?` → `0` and
`ruff format --check src tests ; echo $?` → `0`.

### Step 4: Confirm the suite still passes and the gate is green locally

**Verify**:
- `python -m pytest -q` → `68 passed` (lint changes must not alter behavior; if
  the count changed, a "trivial" fix wasn't trivial — revert it).
- `ruff check src tests && ruff format --check src tests` → **exits 0** (do NOT
  append `; echo ...`: a trailing `echo` always exits 0 and would mask a Ruff
  failure — the whole point is that this line's own exit status is the gate).

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
- [ ] `.github/workflows/test.yml` has a "Lint (Ruff)" step running `ruff check src tests` and `ruff format --check src tests` before the test step
- [ ] `ruff check src tests && ruff format --check src tests` exits 0 (no trailing `echo` — the line's own exit status is the check)
- [ ] `python -m pytest -q` → `68 passed`
- [ ] Only in-scope files changed (`git status --short`); any source edits are import/whitespace-only (confirm via `git diff`)
- [ ] `plans/README.md` status row for 018 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `ruff format src tests` (Step 1) would change the *contents* of any string
  literal or SQL statement — formatting must be whitespace/layout only.
- `ruff check --select E,F,W,I src tests` reports more than a handful of distinct
  rule codes, or any violation whose only fix is a logic change — the ruleset
  scope is then a human decision, not the executor's.
- Any lint "fix" changes the `68 passed` test count.
- The target files don't match the "Current state" excerpts (drift).

## Maintenance notes

- Keep the ruleset small on purpose. Expanding `select` (e.g. adding `B`, `UP`,
  `SIM`) is a separate, opt-in decision — do it in its own PR so the churn is
  reviewable, not bundled with wiring the gate. Because the gate uses `select`
  (not `extend-select`), it is pinned to exactly E/F/W/I and is unaffected by
  Ruff bumping its *default* rule set (which jumped 59→413 in 0.16.0).
- **Markdown code-block formatting is intentionally not gated.** Ruff ≥ 0.16.0
  can format ```python``` blocks inside `.md` files, but the gate targets
  `src tests` only, so the hand-written snippets in `plans/`/`docs/` are left
  alone. If you ever *want* to format those (e.g. `ruff format docs plans`), do
  it as a separate, deliberate change — never widen the CI gate to `.`, which
  would fail on every unformatted doc snippet.
- The Ruff version is pinned for reproducibility; a Dependabot/maintenance bump
  should be reviewed because a new Ruff can introduce new default diagnostics
  (again: `select` shields the *lint* set, but a formatter change across a minor
  version can still shift `ruff format --check` output on `src tests`).
- STACK.md says the code already follows Ruff defaults — if Step 1 contradicts
  that (large format diff), update STACK.md's "Linting / Formatting" note to
  match the reality this plan establishes.
