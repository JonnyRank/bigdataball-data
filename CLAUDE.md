# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An NBA daily fantasy sports (DFS) data pipeline in Python. It ingests player box-score and DraftKings fantasy-log Excel files from Google Drive, loads them into a local SQLite database (`nba_fantasy_logs.db`), computes player averages/projections, and exports results to SQL views and CSVs consumed by Excel-based DFS analysis. There is no web service or app — every entry point is a standalone script.

## Commands

```bash
pip install -r requirements.txt          # install deps

python daily_fantasy_log_upload.py       # MAIN orchestrator — runs the full pipeline
```

`daily_fantasy_log_upload.py` is the orchestrator despite its name. Its `main()` runs, in order: Drive ingestion → player log upload → fantasy log upload → summary tables → slate views → CSV exports → email notification. Each stage is wrapped in try/except, errors are collected into `pipeline_errors`, and the run continues so one failure doesn't abort the rest.

Individual stages can be run standalone (they're imported as modules and also runnable directly):

```bash
python drive_ingestion.py            # download latest .xlsx from Google Drive
python daily_player_upload.py        # ingest player box-score logs only
python create_summary_tables.py      # rebuild fantasy_averages + player-average views
python export_slate_averages_vw.py   # rebuild vw_daily_slate / vw_daily_slate_l30
python export_playoffs_slate_averages_vw.py  # rebuild vw_daily_slate_playoffs
python export_slate_averages_csv.py  # export slate averages to timestamped CSV
python run_db_patch.py               # one-time retroactive player-name fix
python verify_db_patch.py            # verify the name patch
python check_ingest_duplicates.py            # report duplicate (PLAYER_ID, DATE) log rows
python check_ingest_duplicates.py --remove   # back up DB, then delete the duplicates
```

### Tests

A pytest suite lives under `tests/` (CI runs it via `.github/workflows/test.yml` on every push/PR):

```bash
pip install -r requirements-dev.txt      # pytest (separate from runtime deps)
python -m pytest -q                      # full suite
python -m pytest -q tests/test_check_ingest_duplicates.py            # one file
python -m pytest -q -k dedup                                         # by keyword (matches tests with 'dedup')
```

`pytest.ini` sets `pythonpath = .` (so root-level modules import under a bare `pytest`) and `testpaths = tests`. Tests point the scripts at a throwaway data dir via the `BIGDATABALL_DATA_DIR` env override (see below) rather than touching the real DB. `tests/conftest.py` holds the `player_upload` fixture (imports an upload script fresh with the env var set); `tests/helpers.py` writes synthetic input `.xlsx` files. Validate non-tested changes by reading console output and inspecting the SQLite DB directly; run `verify_db_patch.py` after name-mapping changes.

## Architecture and cross-cutting conventions

These patterns are repeated across nearly every script — understanding them is the key to working here:

- **Data-path resolution (per-file, not centralized).** Each DB/upload/export script independently resolves a base path. The upload scripts and `check_ingest_duplicates.py` use a three-way check: `BIGDATABALL_DATA_DIR` env var (explicit override, used by tests and local runs) → `G:\My Drive\Documents\bigdataball` if the `G:` mount exists → local `Data/` under the project root. Older scripts (e.g. `verify_db_patch.py`) still use only the two-way `G:` / `Data/` check with no env override — match the file you're editing. The SQLite DB, input folders, and archive folders all live under this base path. **Exception:** `config.py` hardcodes `BASE_DOWNLOAD_DIR = r"G:\My Drive\..."` with no fallback, and `drive_ingestion.py` downloads to those `config.DATASET_JOBS` paths — so Drive ingestion has no local-`Data/` fallback and effectively requires the `G:` mount.

- **Two database access styles coexist.** Scripts use SQLAlchemy (`create_engine`, `text()`, `engine.begin()`) and pandas `to_sql()`/`read_sql()`, and some use raw `sqlite3`. Match the style of the file you're editing.

- **De-duplication via `log_key`.** Upload scripts build a composite `PLAYER_ID_DATE` key, load all existing keys before processing, skip rows already present, and update the in-memory key set after each file insert. The dedup is **purely in-memory** — `player_logs` / `fantasy_logs` are created implicitly by `to_sql(..., if_exists="append")` and have no PRIMARY KEY or UNIQUE constraint, so nothing at the DB level blocks duplicate `(PLAYER_ID, DATE)` rows. `check_ingest_duplicates.py` is the safety net: it reports such duplicates and (with `--remove`) backs up the DB, then deletes extras keeping the earliest `rowid` per game. After a removal, rebuild the derived data (`create_summary_tables.py` + the slate exports) since duplicates inflate every average.

- **Player name standardization.** `mappings.PLAYER_NAME_MAP` (variant name → canonical DB name, matching DraftKings convention) is the single source of truth. It's applied at ingestion (both upload scripts) and during DraftKings→DB matching (slate exports). When adding a mapping, add it to `mappings.py` and consider running `run_db_patch.py` to fix existing rows retroactively. DraftKings names that fail to match during a run are appended to `{BASE_DATA_PATH}/todo_mappings.txt` (and emailed as warnings) — that file is the worklist of mappings still to add.

- **Excel column sanitization.** On ingestion, headers are normalized (newlines/spaces → underscores, special chars stripped, UPPERCASED), then a `rename_map` applies semantic renames.

- **Fuzzy player matching.** Slate-export scripts read `DKEntries.csv` from `~/Downloads`, detect the header row by scanning for `"Position"`+`"Name + ID"`, then fuzzy-match (`thefuzz`/RapidFuzz) DK names to DB players.

- **File archival.** Processed `.xlsx` files are moved from the input folder to an archive folder via `os.replace()` after a successful insert.

## Database (`nba_fantasy_logs.db`, git-ignored, not committed)

Tables: `fantasy_logs` (raw DFS game logs w/ DK salary/points/position), `player_logs` (raw box scores), `dim_players` (`PLAYER_ID` PK, `PLAYER_NAME`), `fantasy_averages` (aggregated per player/season/team, built by `create_summary_tables.py`), and `map_teams` (raw team name → abbreviation).

Views: `vw_player_averages_regular_season`, `vw_player_averages_playoffs`, `vw_daily_slate`, `vw_daily_slate_l30`, `vw_daily_slate_playoffs`.

> **`map_teams` is referenced by `create_summary_tables.py` but is not created by any script.** It must already exist in the DB before the summary pipeline runs.

## Gotchas

- **Season values are hardcoded** in view-creation scripts, and the filters differ per view: `vw_daily_slate` spans `'2024-25', '2025-26'`, `vw_daily_slate_l30` is `'2025-26'` only, and `vw_daily_slate_playoffs` uses `'2026'`. Update each at the start of a new NBA season.
- **Google Drive auth is interactive** (3-legged OAuth via `auth_manager.py`). First run opens a browser; subsequent runs reuse `token.json`. Cannot run headless without a pre-existing valid `token.json`.
- The DB is regenerated by scripts, never committed (`*.db` is git-ignored). Running anything requires either the Google Drive mount or a local `Data/` dir populated with source `.xlsx` files.

## Environment & secrets

Git-ignored credential files (from Google Cloud Console): `client_secrets.json`, `token.json` (auto-generated on first auth). `.env` variables (loaded via `python-dotenv` in `config.py`): `DRIVE_FOLDER_ID_DFS`, `DRIVE_FOLDER_ID_PLAYER`, `EMAIL_SENDER`, `EMAIL_PASSWORD` (Gmail app password), `EMAIL_RECEIVER`.

## Tooling references

`.github/` contains a `sqlite-dba` agent and `sqlite-optimization` skill for inspecting/optimizing the database, and `.claude/skills/improve/` holds a codebase-audit playbook. `.github/copilot-instructions.md` covers the same ground as this file for the Copilot agent.
