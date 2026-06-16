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
```

There is **no test suite, linter, or build step.** Validate changes by reading console output, inspecting the SQLite DB directly, and running `verify_db_patch.py` after name-mapping changes.

> `requirements.txt` is UTF-16 encoded (it reads as null bytes between characters when viewed as UTF-8). If `pip install -r requirements.txt` fails to parse, re-save it as UTF-8 first.

## Architecture and cross-cutting conventions

These patterns are repeated across nearly every script — understanding them is the key to working here:

- **Dual data-path resolution.** The DB/upload/export scripts each independently check `if os.path.exists(r"G:\My Drive")` and use `G:\My Drive\Documents\bigdataball` on the developer's machine, else fall back to a local `Data/` directory under the project root. The SQLite DB, input folders, and archive folders all live under this base path. This is duplicated per-file rather than centralized. **Exception:** `config.py` hardcodes `BASE_DOWNLOAD_DIR = r"G:\My Drive\..."` with no fallback, and `drive_ingestion.py` downloads to those `config.DATASET_JOBS` paths — so Drive ingestion has no local-`Data/` fallback and effectively requires the `G:` mount.

- **Two database access styles coexist.** Scripts use SQLAlchemy (`create_engine`, `text()`, `engine.begin()`) and pandas `to_sql()`/`read_sql()`, and some use raw `sqlite3`. Match the style of the file you're editing.

- **De-duplication via `log_key`.** Upload scripts build a composite `PLAYER_ID_DATE` key, load all existing keys before processing, skip rows already present, and update the in-memory key set after each file insert.

- **Player name standardization.** `mappings.PLAYER_NAME_MAP` (variant name → canonical DB name, matching DraftKings convention) is the single source of truth. It's applied at ingestion (both upload scripts) and during DraftKings→DB matching (slate exports). When adding a mapping, add it to `mappings.py` and consider running `run_db_patch.py` to fix existing rows retroactively.

- **Excel column sanitization.** On ingestion, headers are normalized (newlines/spaces → underscores, special chars stripped, UPPERCASED), then a `rename_map` applies semantic renames.

- **Fuzzy player matching.** Slate-export scripts read `DKEntries.csv` from `~/Downloads`, detect the header row by scanning for `"Position"`+`"Name + ID"`, then fuzzy-match (`thefuzz`/RapidFuzz) DK names to DB players.

- **File archival.** Processed `.xlsx` files are moved from the input folder to an archive folder via `os.replace()` after a successful insert.

## Database (`nba_fantasy_logs.db`, git-ignored, not committed)

Tables: `fantasy_logs` (raw DFS game logs w/ DK salary/points/position), `player_logs` (raw box scores), `dim_players` (`PLAYER_ID` PK, `PLAYER_NAME`), `fantasy_averages` (aggregated per player/season/team, built by `create_summary_tables.py`), and `map_teams` (raw team name → abbreviation).

Views: `vw_player_averages_regular_season`, `vw_player_averages_playoffs`, `vw_daily_slate`, `vw_daily_slate_l30`, `vw_daily_slate_playoffs`.

> **`map_teams` is referenced by `create_summary_tables.py` but is not created by any script.** It must already exist in the DB before the summary pipeline runs.

## Gotchas

- **Season values are hardcoded** in view-creation scripts (e.g. `'2024-25'`, `'2025-26'`, `'2026'`). Update these at the start of a new NBA season.
- **Google Drive auth is interactive** (3-legged OAuth via `auth_manager.py`). First run opens a browser; subsequent runs reuse `token.json`. Cannot run headless without a pre-existing valid `token.json`.
- The DB is regenerated by scripts, never committed (`*.db` is git-ignored). Running anything requires either the Google Drive mount or a local `Data/` dir populated with source `.xlsx` files.

## Environment & secrets

Git-ignored credential files (from Google Cloud Console): `client_secrets.json`, `token.json` (auto-generated on first auth). `.env` variables (loaded via `python-dotenv` in `config.py`): `DRIVE_FOLDER_ID_DFS`, `DRIVE_FOLDER_ID_PLAYER`, `EMAIL_SENDER`, `EMAIL_PASSWORD` (Gmail app password), `EMAIL_RECEIVER`.

## Tooling references

`.github/` contains a `sqlite-dba` agent and `sqlite-optimization` skill for inspecting/optimizing the database, and `.claude/skills/improve/` holds a codebase-audit playbook. `.github/copilot-instructions.md` covers the same ground as this file for the Copilot agent.
