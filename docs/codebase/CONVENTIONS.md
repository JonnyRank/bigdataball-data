# CONVENTIONS

These are observed from the code, not enforced by any linter (none is configured — see `STACK.md`).

## Naming

- **Files/modules:** `snake_case.py`, named for the action (`daily_player_upload.py`, `export_slate_averages_vw.py`). `_vw` suffix = builds SQL views; `_csv` suffix = exports CSV.
- **Functions:** `snake_case`; public pipeline entry points are verbose verbs — `run_summary_pipeline`, `run_slate_averages_pipeline`, `run_slate_averages_smart_export`, `fix_player_names`.
- **Module-level config constants:** `UPPER_SNAKE_CASE` — `BASE_DATA_PATH`, `DB_PATH`, `LOGS_TABLE_NAME`, `PLAYERS_TABLE_NAME`, `NEW_FILES_FOLDER`, `PROCESSED_FOLDER`.
- **DataFrame columns / DB columns:** `UPPER_SNAKE_CASE` after sanitization (`PLAYER_ID`, `DK_POINTS`, `SEASON_SEGMENT`). This is enforced by the column-sanitization step, not just convention.
- **Views:** `vw_` prefix (`vw_daily_slate`, `vw_player_averages_regular_season`).
- **Note:** the orchestrator `daily_fantasy_log_upload.py` still opens with a stale `# main.py` comment header (`daily_fantasy_log_upload.py:1`); several modules carry `# NEW:` / `# From debug output` development-artifact comments.

## Formatting

- 4-space indentation; **double-quoted** strings throughout; trailing commas in multi-line literals. Consistent with Black output but **not enforced** by any committed config.
- Windows paths use raw strings: `r"G:\My Drive\Documents\bigdataball"`.
- Liberal section-banner comments (`# --- 1. Configuration ---`, `# --- 4b. De-duplicate Logs ---`) structure long procedural functions.

## Imports

- Stdlib, then third-party, then local — generally but not strictly grouped.
- Local modules imported **package-relative** (`from . import config`, `from . import mappings`, `from .auth_manager import ...`) inside the `src/bigdataball/` package — this is why `pytest.ini` sets `pythonpath = src`. This is the result of the plan 009 src-layout refactor (DONE); the module-reference names at call sites are unchanged, only the import lines.
- `src/bigdataball/__init__.py` marks the package; `tests/__init__.py` exists so `from tests.helpers import ...` works.

## Path Resolution (the central cross-cutting convention)

**Centralized in `paths.py` (plan 005, DONE).** Every DB-touching script resolves its base data dir the same way — `BASE_DATA_PATH = paths.resolve_base_data_path()` — which applies one precedence: `BIGDATABALL_DATA_DIR` env override → `G:\My Drive\...` mount → local `Data/` under the repo root. When editing path logic, change `paths.py`, not the call sites. The old per-script 3-way/2-way idioms have been fully collapsed.

`config.py` remains the exception: its `BASE_DOWNLOAD_DIR` (Drive *download* target) is a hardcoded `G:` path with no fallback and does **not** go through `paths.py`.

## Database Access

- Pipeline/aggregation scripts: SQLAlchemy `create_engine(f"sqlite:///{DB_PATH}")`, `pandas.read_sql`/`to_sql`, and `with engine.begin():` for DDL transactions.
- Maintenance scripts (`check_ingest_duplicates.py`, `run_db_patch.py`, `verify_db_patch.py`, `create_log_indexes.py`): raw `sqlite3.connect` + cursor.
- **UNIQUE-index backstop.** Log tables have no declared PK, but each upload path calls `ensure_unique_index()` (`CREATE UNIQUE INDEX IF NOT EXISTS idx_<table>_player_date ON <table> ("PLAYER_ID", "DATE")`) from `initialize_database()` and after each `to_sql(append)`. It swallows `"no such table"` on the first run (the table doesn't exist until `to_sql` creates it) and is otherwise idempotent. When adding a new log-style table, follow the same pattern.
- **Tests must dispose the engine** before tmp cleanup so Windows can delete the locked SQLite file (`tests/conftest.py:24-27`).

## Player Name Standardization

- `mappings.PLAYER_NAME_MAP` (variant → canonical, DraftKings convention) is the **single source of truth**. Applied at both ingestion points and in DK→DB matching. When adding a mapping, add it to `mappings.py` and consider `run_db_patch.py` to fix existing rows.

## SQL Construction

- View/query SQL built with f-strings. Player names from the DB are escaped with `.replace("'", "''")` before interpolation into `IN (...)` lists (`export_slate_averages_vw.py:102`). Table/column names in maintenance scripts are hardcoded constants, never user input (`run_db_patch.py:28-35`). Value parameters in maintenance scripts use bound params (`?`) (`run_db_patch.py:46-49`).

## Error Handling

- **Orchestrator:** every stage in a try/except; the exception message is appended to `pipeline_errors` and the run continues (`daily_fantasy_log_upload.py:80-347`). Reported via email at the end.
- **Per-file ingestion loop:** on error, print, `break` out of the file loop (the failed file is **not** archived), so it's retried next run (`daily_player_upload.py:259-262`).
- **First-run table-missing:** detected by string match `"no such table"` in the exception, then an empty DataFrame is created (`daily_player_upload.py:87-95`).
- **Maintenance scripts:** `sqlite3.OperationalError` filtered on `"no such table"`/`"no such column"` to skip absent tables (`run_db_patch.py:61-67`).
- Style is print-based logging; **no `logging` module** is used anywhere.

## Season Filters

Season constants live in **`seasons.py`** (plan 007, DONE). At the start of each NBA season, update the three values there — nothing else needs changing:
- `SLATE_SEASONS` — multi-season span for `vw_daily_slate` and the main CSV export
- `L30_SEASON` — current regular season for L30 views/CSVs (must equal `SLATE_SEASONS[-1]`)
- `PLAYOFFS_SEASON` — current playoff year for `vw_daily_slate_playoffs`

The export scripts interpolate these via `{seasons.slate_seasons_sql()}` / `{seasons.L30_SEASON}` / `{seasons.PLAYOFFS_SEASON}`.

## Evidence

- `paths.py` (`resolve_base_data_path`, single precedence chain)
- `daily_player_upload.py:18,34-71,87-104,122-161`
- `daily_fantasy_log_upload.py:1,25,41-78,80-347`
- `create_summary_tables.py:10` (path via `paths`)
- `dk_matching.py:10-95`, `export_slate_averages_vw.py:27-64`
- `run_db_patch.py:28-49,61-67`
- `tests/conftest.py:18-27`
- `pytest.ini:2`
- `mappings.py:1-17`, `seasons.py`
