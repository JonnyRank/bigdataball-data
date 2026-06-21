# Copilot Instructions for bigdataball-data

## Project Overview

This is an **NBA daily fantasy sports (DFS) data pipeline** built in Python. It ingests player box-score and DraftKings fantasy-log data from Google Drive (Excel files), loads it into a local **SQLite** database (`nba_fantasy_logs.db`), computes player averages and projections, and exports results to CSV and SQL views for use in Excel-based DFS analysis.

## Repository Structure

| File | Purpose |
|---|---|
| `daily_fantasy_log_upload.py` | **Main entry point / orchestrator.** Runs the full pipeline: Drive ingestion → player log upload → fantasy log upload → summary tables → slate views → CSV exports → email notification. |
| `daily_player_upload.py` | Ingests player box-score `.xlsx` files into the `player_logs` table. De-duplicates against existing data. |
| `drive_ingestion.py` | Downloads latest `.xlsx` files from Google Drive shared folders using the Drive API v3. |
| `auth_manager.py` | Google OAuth 2.0 authentication (3-legged flow with `client_secrets.json` / `token.json`). |
| `config.py` | Central configuration: Google Drive folder IDs, file paths, credential paths, email settings. Reads secrets from `.env`. |
| `mappings.py` | `PLAYER_NAME_MAP` dictionary — maps variant player names (e.g., from DraftKings) to canonical database names. |
| `create_summary_tables.py` | Builds the `fantasy_averages` table from raw logs (aggregated stats per player/season/team) and creates convenience views. |
| `export_slate_averages_vw.py` | Reads `DKEntries.csv` from Downloads, fuzzy-matches players to the DB, and creates `vw_daily_slate` / `vw_daily_slate_l30` views. |
| `export_playoffs_slate_averages_vw.py` | Same as above but for playoff data — creates `vw_daily_slate_playoffs` view. |
| `export_slate_averages_csv.py` | Same fuzzy-match workflow but exports results to timestamped CSV files instead of views. |
| `email_notifier.py` | Sends pipeline success/error email notifications via Gmail SMTP. |
| `run_db_patch.py` | One-time utility to retroactively fix player names across all tables using `mappings.PLAYER_NAME_MAP`. |
| `verify_db_patch.py` | Verifies the name patch was applied correctly. |
| `requirements.txt` | Pinned Python dependencies. |

## Technology Stack

- **Python 3** (no specific version pinned; uses f-strings, `pathlib` not used)
- **SQLite** via **SQLAlchemy** (`create_engine`, `text()`, `engine.begin()`) and raw `sqlite3`
- **pandas** for data manipulation and `to_sql()` / `read_sql()` for DB I/O
- **openpyxl** for reading `.xlsx` files
- **google-api-python-client** + **google-auth-oauthlib** for Google Drive API
- **thefuzz** (formerly fuzzywuzzy) + **RapidFuzz** for player name fuzzy matching
- **python-dotenv** for `.env` file loading

## Database Schema

The SQLite database (`nba_fantasy_logs.db`) contains:

### Tables
- **`fantasy_logs`** — Raw DFS game logs (one row per player per game). Columns: `SEASON_SEGMENT`, `GAME_ID`, `PLAYER_ID`, `PLAYER`, `DATE`, `TEAM`, `OPPONENT`, `VENUE`, `STARTED`, `MINUTES`, stat columns, `DK_POSITION`, `DK_SALARY`, `DK_POINTS`, `DAYS_REST`, `USAGE`.
- **`player_logs`** — Raw player box-score logs. Similar structure but without DK-specific columns.
- **`dim_players`** — Player dimension table (`PLAYER_ID` INTEGER PK, `PLAYER_NAME` TEXT).
- **`map_teams`** — Team name mapping table (`RAW_TEAM_NAME` → `TEAM_ABBREVIATION`). Not created by these scripts (manually managed).
- **`fantasy_averages`** — Aggregated averages per player/season/team, computed by `create_summary_tables.py`.

### Views
- `vw_player_averages_regular_season` — Regular season averages from `fantasy_averages`.
- `vw_player_averages_playoffs` — Playoff averages from `fantasy_averages`.
- `vw_daily_slate` — Current DraftKings slate players (regular season, multi-season).
- `vw_daily_slate_l30` — Current slate with last-30-days FPPM metric.
- `vw_daily_slate_playoffs` — Current DraftKings slate for playoffs.

## Key Patterns and Conventions

### Data Path Resolution
All scripts use a dual-path strategy:
```python
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
```
On the developer's machine, data lives on Google Drive (G: drive). On other machines (including CI), it falls back to a local `Data/` subdirectory.

### De-duplication Strategy
Both upload scripts create a composite `log_key` (`PLAYER_ID_DATE`) to prevent duplicate game-log insertions. They load existing keys before processing, check new data against them, and update the in-memory set after each file insert.

### Player Name Standardization
`mappings.PLAYER_NAME_MAP` is the single source of truth for name corrections. It is used at ingestion time (both upload scripts) and for DraftKings → DB matching (slate export scripts). The `run_db_patch.py` script applies mappings retroactively to existing data.

### Column Sanitization
Excel column headers are sanitized on ingestion: newlines and spaces → underscores, special chars removed, converted to UPPERCASE. Then a `rename_map` dictionary applies semantic renaming.

### File Archival
After successful processing, `.xlsx` files are moved from the input folder to an archive folder using `os.replace()`.

## Environment & Secrets

Required environment variables (loaded from `.env`):
- `DRIVE_FOLDER_ID_DFS` — Google Drive folder ID for DFS feed files
- `DRIVE_FOLDER_ID_PLAYER` — Google Drive folder ID for player feed files
- `EMAIL_SENDER` — Gmail address for notifications
- `EMAIL_PASSWORD` — Gmail app password
- `EMAIL_RECEIVER` — Notification recipient

Required credential files (git-ignored):
- `client_secrets.json` — Google OAuth client credentials (from GCP Console)
- `token.json` — Cached OAuth token (auto-generated on first auth)

## How to Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** The `requirements.txt` file may contain encoding artifacts (null bytes between characters). If `pip install` fails with a parsing error, re-save the file with standard UTF-8 encoding before retrying.

## How to Run

The main pipeline entry point is:
```bash
python daily_fantasy_log_upload.py
```

Individual scripts can also be run standalone:
```bash
python daily_player_upload.py          # Just player box-score ingestion
python drive_ingestion.py              # Just Google Drive download
python create_summary_tables.py        # Just rebuild averages + views
python export_slate_averages_vw.py     # Just rebuild slate views
python export_slate_averages_csv.py    # Just export slate CSV
python run_db_patch.py                 # One-time name fix
python verify_db_patch.py              # Verify name fix
```

## Testing

There are **no automated tests** in this repository. Validate changes by:
1. Reviewing the script's console output for errors
2. Inspecting the SQLite database directly (e.g., via the `sqlite-dba` agent or a SQLite browser)
3. Running `verify_db_patch.py` after name-mapping changes

## Important Notes for Making Changes

- **No test suite exists.** Be extra careful with changes and validate manually.
- **Database is not committed.** The `.db` file is git-ignored. Scripts expect either a Google Drive mount or a local `Data/` directory with the `.xlsx` source files.
- **Google Drive auth requires interactive browser login** on first use — this cannot run in headless CI without a pre-existing `token.json`.
- **`map_teams` table** is referenced by `create_summary_tables.py` but is not created by any script in the repo. It must exist in the database before running the summary pipeline.
- **Season filters live in `seasons.py`** — update the three constants there (`SLATE_SEASONS`, `L30_SEASON`, `PLAYOFFS_SEASON`) when starting a new NBA season. No changes needed in the export scripts.
- When adding a new player name mapping, add it to `mappings.py` and consider running `run_db_patch.py` to retroactively fix existing data.
- The `daily_fantasy_log_upload.py` file is the main orchestrator despite its name suggesting it only handles fantasy logs.
