# CONCERNS

Production-code concerns first; test-only and intent-divergence items are separated out below. No `TODO`/`FIXME`/`HACK` markers exist in production code (scan: "None found").

## Intent vs. Reality Divergences

1. ~~**Misleading commit + planned `src/` layout not done.**~~ **Resolved by plan 009 (DONE, 2026-07-24).** All runtime modules now live under the installable `src/bigdataball/` package with package-relative imports, a `pyproject.toml` packaging manifest, `pytest.ini` `pythonpath = src`, and CI running `pip install -e .`. The earlier divergence — commit `90bc0ab` was titled as the refactor but only added the plan document — no longer applies; the refactor has shipped. *Evidence:* `src/bigdataball/`, `pyproject.toml`, `plans/README.md` (plan 009 row: DONE).
2. **Stale setup guide describes a non-existent `main.py`.** `BigDataBall-Ingestion-Pipeline-Setup-Guide.md` (git-ignored as a design doc) presents `main.py` as the ingestion entry point and an older `orderBy='name'` Drive query. The real entry point is `drive_ingestion.py`, which sorts by `createdTime` to handle date rollovers. Treat `CLAUDE.md` as authoritative, not the setup guide. *Evidence:* setup guide §"Step 4", `drive_ingestion.py:29`.
3. **Orchestrator name vs. role.** `daily_fantasy_log_upload.py` is the *whole-pipeline* orchestrator, not just a fantasy-log uploader; it still opens with a stale `# main.py` header comment. Documented in `CLAUDE.md`; deliberately not renamed (would break the documented invocation). *Evidence:* `daily_fantasy_log_upload.py:1,69-395`, `plans/README.md:73-74`.

## Data-Integrity Concerns

4. ~~**No DB-level uniqueness on log tables.**~~ **Largely resolved by plan 012 (DONE).** All three log tables now carry a UNIQUE index `idx_<table>_player_date` on `("PLAYER_ID", "DATE")`, created by `ensure_unique_index()` on every ingest and backfillable on an offseason DB via `create_log_indexes.py`. A dedup miss now raises `IntegrityError` rather than silently duplicating. The in-memory `log_key` set is still the first-line filter, and `check_ingest_duplicates.py` remains the cleanup tool for any pre-index duplicates. *Evidence:* `daily_player_upload.py:34-71,254`, `absence_ingestion.py:54-65`, `create_log_indexes.py`.
5. **The in-memory dedup remains the primary filter.** Issue #6 / plan 003 (DONE) fixed the multi-file re-insertion bug, and plan 004 (DONE) preserved the regular-season unmatched-players worklist. Plan 012's UNIQUE index (see #4) now backstops the in-memory `log_key` set, so a regression fails loudly instead of silently — the design is materially less fragile than before, though the in-memory set is still what avoids the exception on the happy path. *Evidence:* `check_ingest_duplicates.py:7-18`, `plans/README.md`.
6. ~~**`map_teams` is read but never created by any Python script.**~~ **Resolved by plan 008 (DONE).** `seed_map_teams.py` creates and populates `map_teams`; run it once on a fresh DB, then re-run after the first real ingestion so `RAW_TEAM_NAME` values derive from actual `fantasy_logs.TEAM` strings (`BIGDATABALL_SEED_FORCE=1` overwrites a populated table). `create_summary_tables.py:40-52` still guards for the table and aborts cleanly if it's missing. *Evidence:* `seed_map_teams.py`, `create_summary_tables.py:40-52`.
7. **Derived data is fully recomputed each run.** `fantasy_averages` is `if_exists="replace"`, so any duplicate/garbage log rows inflate every average until cleaned and rebuilt. Operationally this couples `check_ingest_duplicates.py --remove` with a mandatory re-run of the summary + slate exports. *Evidence:* `create_summary_tables.py:291-297`, `check_ingest_duplicates.py:264-272`.

## Maintainability / Tech Debt

8. ~~**Triplicated DraftKings load + fuzzy-match logic.**~~ **Resolved by plan 006 (DONE).** The DKEntries.csv load, header detection, `PLAYER_NAME_MAP` application, and `thefuzz` match (score ≥ 90) now live once in `dk_matching.py` (`find_dk_file_path`/`load_dk_names`/`match_names`/`to_sql_in_list`); all three export scripts call it. *Evidence:* `dk_matching.py:10-95`, `export_slate_averages_vw.py:27-64`.
9. ~~**Decentralized, inconsistent path resolution.**~~ **Resolved by plan 005 (DONE).** DB path resolution is centralized in `paths.resolve_base_data_path()` (`BIGDATABALL_DATA_DIR` → `G:` mount → local `Data/`); every DB-touching script imports it. The only remaining hardcoded, no-fallback `G:` path is `config.py`'s `BASE_DOWNLOAD_DIR` for Drive *downloads* (see #13). *Evidence:* `paths.py`, `config.py:7`.
10. ~~**Hardcoded season filters that differ per view.**~~ **Resolved by plan 007 (DONE).** Season constants now live in `seasons.py`; the three export scripts source them via `{seasons.slate_seasons_sql()}` / `{seasons.L30_SEASON}` / `{seasons.PLAYOFFS_SEASON}`. Annual rollover is a single edit to `seasons.py`.
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

From `git` history (last 90 days, top of list): `plans/README.md` (27), `CLAUDE.md` (9), `daily_fantasy_log_upload.py` (8), `daily_player_upload.py` (6), `absence_ingestion.py` (5), `export_slate_averages_vw.py` (4), plus the plan docs and their test files. Among *pipeline* code the orchestrator (`daily_fantasy_log_upload.py`), the two upload paths, and the newer `absence_ingestion.py` see the most churn — expect ongoing edits there. *Evidence:* `git log --since="90 days ago" --name-only`.

## Test-Only Items (coverage gaps, not production debt)

- The suite is now **56 tests across 9 modules** (see `TESTING.md`). Remaining coverage gaps: `create_summary_tables.py` (plan 011, TODO), the view-building bodies of the export scripts, the end-to-end orchestrator, and the Drive/email modules. These are coverage gaps, not runtime bugs. No coverage tooling configured.

## Evidence

- `plans/README.md` (plan status table + rejected findings)
- `git show --stat 90bc0ab` (plan-only commit)
- `create_summary_tables.py:40-52,291-297`
- `check_ingest_duplicates.py:7-18,264-272`
- `daily_player_upload.py:34-71,254` / `absence_ingestion.py:54-65` (UNIQUE index)
- `paths.py`, `dk_matching.py`, `seed_map_teams.py`, `create_log_indexes.py`
- `config.py:7,34`
- `auth_manager.py:20-37`
- `git log --since="90 days ago" --name-only` (high-churn list)
