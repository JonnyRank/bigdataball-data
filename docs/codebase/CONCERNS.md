# CONCERNS

Production-code concerns first; test-only and intent-divergence items are separated out below. No `TODO`/`FIXME`/`HACK` markers exist in production code (scan: "None found").

## Intent vs. Reality Divergences

1. **Misleading commit + planned `src/` layout not done.** Commit `90bc0ab` is titled "plan 009: Convert flat layout to src/bigdataball/ package" but it only **added the plan document** — no `src/` directory exists and all modules remain at the repo root. Plan 009 status is `TODO` in `plans/README.md:22`. Anyone reading the git log alone would believe the refactor shipped. *Evidence:* `git show --stat 90bc0ab`, absence of `src/`, `plans/README.md:22`.
2. **Stale setup guide describes a non-existent `main.py`.** `BigDataBall-Ingestion-Pipeline-Setup-Guide.md` (git-ignored as a design doc) presents `main.py` as the ingestion entry point and an older `orderBy='name'` Drive query. The real entry point is `drive_ingestion.py`, which sorts by `createdTime` to handle date rollovers. Treat `CLAUDE.md` as authoritative, not the setup guide. *Evidence:* setup guide §"Step 4", `drive_ingestion.py:29`.
3. **Orchestrator name vs. role.** `daily_fantasy_log_upload.py` is the *whole-pipeline* orchestrator, not just a fantasy-log uploader; it still opens with a stale `# main.py` header comment. Documented in `CLAUDE.md`; deliberately not renamed (would break the documented invocation). *Evidence:* `daily_fantasy_log_upload.py:1,69-395`, `plans/README.md:73-74`.

## Data-Integrity Concerns

4. **No DB-level uniqueness on log tables.** `player_logs`/`fantasy_logs` are created implicitly by `to_sql(if_exists="append")` with no PRIMARY KEY or UNIQUE constraint. De-duplication is **purely in-memory** via the `log_key` set; nothing at the DB layer prevents duplicate `(PLAYER_ID, DATE)` rows. `check_ingest_duplicates.py` exists solely as the after-the-fact safety net. *Evidence:* `daily_player_upload.py:232-244`, `check_ingest_duplicates.py:14-18`.
5. **The dedup-bug class is documented but the root design is fragile.** Issue #6 / plan 003 (DONE) fixed the specific multi-file re-insertion bug, but the architecture still relies on rebuilding an in-memory set correctly rather than a DB constraint, so regressions remain possible. Plan 004 (`TODO`, "Preserve regular-season unmatched-players worklist") and the dedup design are open items. *Evidence:* `check_ingest_duplicates.py:7-18`, `plans/README.md:16-17`.
6. **`map_teams` is read but never created by any Python script.** `create_summary_tables.py` requires it and aborts cleanly if missing, but a fresh DB will silently lack it until someone runs `create_team_map_table.sql` manually (which is git-ignored via `*.sql`). Plan 008 (`TODO`) addresses seeding it. *Evidence:* `create_summary_tables.py:40-59`, `create_team_map_table.sql`, `.gitignore:30`.
7. **Derived data is fully recomputed each run.** `fantasy_averages` is `if_exists="replace"`, so any duplicate/garbage log rows inflate every average until cleaned and rebuilt. Operationally this couples `check_ingest_duplicates.py --remove` with a mandatory re-run of the summary + slate exports. *Evidence:* `create_summary_tables.py:291-297`, `check_ingest_duplicates.py:264-272`.

## Maintainability / Tech Debt

8. **Triplicated DraftKings load + fuzzy-match logic.** The DKEntries.csv load, header detection, `PLAYER_NAME_MAP` application, and `thefuzz` match (score ≥ 90) are copy-pasted across `export_slate_averages_vw.py`, `export_playoffs_slate_averages_vw.py`, and `export_slate_averages_csv.py`. A change must be made in three places. Plan 006 (`TODO`) proposes extracting a helper. *Evidence:* `export_slate_averages_vw.py:37-98`, `export_playoffs_slate_averages_vw.py:37-98`, `export_slate_averages_csv.py:39-99`.
9. **Decentralized, inconsistent path resolution.** Three different idioms coexist: 3-way (with `BIGDATABALL_DATA_DIR`), 2-way (no env override), and `config.py`'s hardcoded no-fallback `G:` path. Editing path logic requires touching many files and remembering which form each uses. Plan 005 (`TODO`) proposes a single `paths` module. *Evidence:* `daily_player_upload.py:21-27`, `create_summary_tables.py:13-17`, `config.py:7`.
10. **Hardcoded season filters that differ per view.** Season strings (`'2024-25','2025-26'` / `'2025-26'` / `'2026'`) are duplicated across the export scripts and must each be updated at season rollover — easy to miss one. Plan 007 (`TODO`). *Evidence:* `export_slate_averages_vw.py:128,172`, `export_playoffs_slate_averages_vw.py:128`.
11. **Duplicated `os.makedirs(..., exist_ok=True)` lines and dead commented code.** e.g. `daily_player_upload.py:35-36` (line repeated) and the dead summary-pipeline block at `daily_player_upload.py:267-270` after `return`. Cosmetic; noted in `plans/README.md` as not worth a dedicated plan. *Evidence:* `daily_player_upload.py:35-36,267-270`, `daily_fantasy_log_upload.py:43-44`.
12. **No structured logging.** All observability is `print()` + the end-of-run email; no log levels, no persisted log, no error tracking. Hard to diagnose a failed scheduled run after the fact. *Evidence:* absence of `logging` imports across all modules.

## Operational / Environment Risks

13. **Windows / `G:` mount coupling.** `config.BASE_DOWNLOAD_DIR` is a hardcoded `G:\My Drive\...` path with no fallback, so Drive ingestion only works on the synced Windows machine. CI runs on Linux but only exercises the env-override path via tests. *Evidence:* `config.py:7`, `drive_ingestion.py` (downloads to `config.DATASET_JOBS` paths).
14. **Interactive OAuth blocks headless runs.** First Drive auth opens a browser; a scheduled/headless run is impossible without a pre-existing valid `token.json`. Token refresh depends on the project being "In Production" in GCP. *Evidence:* `auth_manager.py:20-37`, setup guide §"Consent Screen Strategy".
15. **Pipeline trigger lives outside the repo.** The daily run is driven by **Windows Task Scheduler** on the maintainer's machine — there is no committed scheduler config, so the trigger is undiscoverable from the repo alone and is tied to one host (which must also hold a valid `token.json`). Combined with #13/#14, the pipeline is effectively single-machine. *Source:* maintainer (2026-06-17).

## Security Notes (reviewed, low risk)

- Credentials (`.env`, `token.json`, `client_secrets.json`) are git-ignored; nothing sensitive is committed (`.gitignore:4-6`).
- SQL `IN (...)` lists are built with f-strings, but player names are DB-sourced and single-quote-escaped (`.replace("'", "''")`), and table/column names in maintenance scripts are hardcoded constants — not meaningfully exploitable here. Reviewed and rejected as a finding in `plans/README.md:61-65`.
- Gmail uses an app password from env (`config.py:34`), not a hardcoded secret.

## High-Churn Files (watch for hidden complexity)

From `git` history (last 90 days, top of list): `plans/README.md` (6), `player_top_fantasy_performances.sql` (4), `CLAUDE.md` (3), `.gitignore` (3), `daily_fantasy_log_upload.py` (2), `mappings.py` (2). The orchestrator and `mappings.py` are the only frequently-touched *pipeline* files — expect ongoing edits there. *Evidence:* `docs/codebase/.codebase-scan.txt` HIGH-CHURN section.

## Test-Only Items (coverage gaps, not production debt)

- No tests for the orchestrator, summary, export, Drive, or email modules (see `TESTING.md`). These are coverage gaps, not runtime bugs. No coverage tooling configured.

## Evidence

- `plans/README.md:13-22,61-74` (plan statuses + rejected findings)
- `git show --stat 90bc0ab` (plan-only commit)
- `create_summary_tables.py:40-59,291-297`
- `check_ingest_duplicates.py:7-18,264-272`
- `config.py:7,34`
- `auth_manager.py:20-37`
- `export_slate_averages_vw.py:37-98,128,172`
- `daily_player_upload.py:35-36,232-244,267-270`
- `docs/codebase/.codebase-scan.txt` (TODO scan: none; high-churn list)
