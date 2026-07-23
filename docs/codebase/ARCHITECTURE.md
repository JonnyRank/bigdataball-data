# ARCHITECTURE

## Overview

A single-machine, batch NBA DFS data pipeline. There is no service, API, or long-running process — the system is a sequence of scripts that move Excel files from Google Drive into a local SQLite database, compute per-player averages/projections, and emit SQL views + CSVs consumed by Excel-based DFS analysis. Orchestration is procedural: one `main()` calls each stage in order.

## Pipeline Data Flow

Orchestrated by `daily_fantasy_log_upload.py:main()` (`daily_fantasy_log_upload.py:69-395`), in order:

```
Google Drive (.xlsx)
   │  drive_ingestion.main()           # download latest dfs-feed + player-feed
   ▼
Daily_Fantasy_Logs/  &  Daily_Player_Logs/   (input drop folders)
   │  daily_player_upload.main()       # box scores → player_logs (+ learn dim_players)
   │    └─ absence_ingestion.ingest_absences()  # DNP-DND-NWT sheet → player_absences (+ learn dim_players)
   │  daily_fantasy_log_upload (inline loop)  # DFS logs → fantasy_logs (+ dim_players)
   ▼
SQLite: player_logs, fantasy_logs, dim_players, player_absences
   │  create_summary_tables.run_summary_pipeline()
   ▼
fantasy_averages  +  vw_player_averages_regular_season / _playoffs
   │  export_slate_averages_vw / _playoffs_vw    # filter to today's DK slate
   ▼
vw_daily_slate, vw_daily_slate_l30, vw_daily_slate_playoffs
   │  export_slate_averages_csv                  # timestamped CSVs
   ▼
csv_exports/*.csv   →  email_notifier.send_email_alert()   (summary / errors / warnings)
```

After ingestion, processed `.xlsx` files are moved to `Archived_*` folders via `os.replace()`.

## Layers / Components

There are no formal layers (no domain/data/service split). Functional groupings:

1. **Acquisition** — `auth_manager.py` (OAuth) + `drive_ingestion.py` (Drive list/download) + `config.py` (job definitions).
2. **Ingestion / ETL** — `daily_player_upload.py` and the inline loop in `daily_fantasy_log_upload.py`. Read Excel → sanitize headers → rename → standardize names (`mappings.py`) → dedup → `to_sql(append)`. `absence_ingestion.py` is a shared module (no module-level path/engine — receives an injected `engine`) that reads the same player-feed file's second sheet (`DNP-DND-NWT`) into `player_absences`; it's called from `daily_player_upload.py:main()` after box scores are loaded for that file, and also from the standalone one-shot backfill CLI `backfill_player_absences.py` (reads already-archived files in place, does not move them).
3. **Aggregation** — `create_summary_tables.py`: joins logs with `dim_players` + `map_teams`, derives `SEASON_TYPE`/`SEASON_KEY`, aggregates to `fantasy_averages`, builds player-average views.
4. **Slate selection / export** — the three `export_*` scripts, all sharing `dk_matching.py`: read `~/Downloads/DKEntries.csv`, fuzzy-match DK names to DB, build slate views / CSVs scoped to the current slate (season windows from `seasons.py`).
5. **Maintenance / setup** — `seed_map_teams.py` (create + populate `map_teams`), `create_log_indexes.py` (backfill the plan-012 UNIQUE indexes), `check_ingest_duplicates.py` (dedup safety net), `run_db_patch.py` / `verify_db_patch.py` (retroactive name fixes), `patch_absence_column_names.py` (one-time `player_absences` column rename to the `DATE`/`PLAYER` convention).
6. **Notification** — `email_notifier.py` (SMTP over SSL).

## Key Architectural Patterns

- **Centralized DB path resolution (`paths.py`).** Every DB-touching script calls `paths.resolve_base_data_path()` for its `BASE_DATA_PATH`: `BIGDATABALL_DATA_DIR` env override → `G:\My Drive\...` if the mount exists → local `Data/` under the repo root (`paths.py`, plan 005). The old per-script 3-way/2-way duplication is gone. **Exception:** `config.py:7` (Drive *download* dir) still hardcodes the `G:` path with **no fallback**, so Drive ingestion — but not the rest of the pipeline — requires the mount.

- **Resilient stage orchestration.** Each pipeline stage is wrapped in try/except; errors are appended to `pipeline_errors` and the run continues so one failure doesn't abort the rest (`daily_fantasy_log_upload.py:80-347`). The final email reports success or the collected errors.

- **Two-layer de-duplication (`log_key` + UNIQUE index).** Upload scripts build a composite `PLAYER_ID + "_" + DATE` key, load existing `(PLAYER_ID, DATE)` from the DB, skip rows already present, and `.update()` the in-memory key set after each insert. As of plan 012 a DB-level **UNIQUE index** `idx_<table>_player_date` on `("PLAYER_ID", "DATE")` now backstops this: `ensure_unique_index()` runs from `initialize_database()` (existing tables) and again after each `to_sql(if_exists="append")` (idempotent, `IF NOT EXISTS`), so a dedup miss fails loudly with `IntegrityError` instead of silently inflating averages (`daily_player_upload.py:34-71,254`, `daily_fantasy_log_upload.py:41-78,285`, `absence_ingestion.py:54-65`). `create_log_indexes.py` backfills the index on an existing offseason DB; `check_ingest_duplicates.py` remains the after-the-fact cleanup for any pre-index duplicates.

- **Two DB access styles coexist.** SQLAlchemy `create_engine`/`text()`/`engine.begin()` + pandas `to_sql`/`read_sql` in the pipeline scripts; raw `sqlite3` in `check_ingest_duplicates.py`, `run_db_patch.py`, `verify_db_patch.py`. Match the file you're editing.

- **Excel column sanitization → semantic rename.** Headers are normalized (newlines/hyphens/spaces → `_`, special chars stripped, UPPERCASED) then a per-script `rename_map` applies semantic names (`daily_player_upload.py:122-161`, `daily_fantasy_log_upload.py:165-204`).

- **Fuzzy DraftKings matching (shared `dk_matching.py`).** The DKEntries.csv load, header detection (scan first 50 lines for `"Position"` + `"Name + ID"`), explicit `PLAYER_NAME_MAP` pass, and `thefuzz.process.extractOne` with a **score ≥ 90** threshold were extracted into `dk_matching.py` (plan 006) — all three export scripts call `find_dk_file_path()` / `load_dk_names()` / `match_names()` / `to_sql_in_list()`. Misses are returned as `unmatched_names` (`dk_matching.py:10-95`, `export_slate_averages_vw.py:27-64`).

- **Views rebuilt by DROP + CREATE in a transaction.** `with engine.begin(): DROP VIEW IF EXISTS; CREATE VIEW` (`create_summary_tables.py:343-345`, export scripts). Player names are escaped (`.replace("'", "''")`) before being interpolated into `IN (...)` lists.

## Database Schema

Tables (all three log tables carry a UNIQUE index `idx_<table>_player_date` on `("PLAYER_ID", "DATE")` as of plan 012 — no declared PK, but the index enforces the natural key): `fantasy_logs`, `player_logs`, `dim_players` (`PLAYER_ID` PK), `fantasy_averages` (rebuilt `if_exists="replace"`), `map_teams` (`RAW_TEAM_NAME` PK → `TEAM_ABBREVIATION`), `player_absences` (one row per player per missed game from the player-feed's `DNP-DND-NWT` sheet; columns `DATE`, `GAME_ID` (INTEGER, matching `player_logs.GAME_ID`), `TEAM`, `OPPONENT`, `PLAYER_ID`, `PLAYER`, `STATUS`, `REASON`, and derived `ABSENCE_TYPE` — `'DNP-CD'` when `REASON == "COACH'S DECISION"`, else `'INJURY/ILLNESS/OTHER'`. Conflict policy: **box score wins at ingest** — a row is skipped if `player_logs` already has a box score for the same `(PLAYER_ID, DATE)` (re-keyed from GAME_ID by plan 012). Populated by `absence_ingestion.py`, called from `daily_player_upload.py` and `backfill_player_absences.py`).

Views: `vw_player_averages_regular_season`, `vw_player_averages_playoffs` (built by summary), `vw_daily_slate`, `vw_daily_slate_l30`, `vw_daily_slate_playoffs` (built by exports).

> `map_teams` is **read** by `create_summary_tables.py` and **created by `seed_map_teams.py`** (plan 008 DONE) — run it once on a fresh DB before the summary pipeline, then re-run after the first real ingestion so `RAW_TEAM_NAME` values derive from actual `fantasy_logs.TEAM` strings (`BIGDATABALL_SEED_FORCE=1` overwrites a populated table). `create_summary_tables.py:40-52` still guards for it and aborts cleanly if it's missing.

## Derived-Data Invalidation

`fantasy_averages` and all averages are recomputed from the full log tables on each run (`if_exists="replace"`). Duplicate log rows therefore inflate every average — after `check_ingest_duplicates.py --remove`, the summary + slate exports must be re-run (`check_ingest_duplicates.py:264-272`).

## Evidence

- `daily_fantasy_log_upload.py:69-395` (orchestration, try/except per stage)
- `daily_player_upload.py:71-244` (dedup `log_key` flow, `to_sql(append)`)
- `absence_ingestion.py` (DNP-DND-NWT sheet → `player_absences`, box-score-wins conflict filter, dim_players learning)
- `backfill_player_absences.py` (one-shot CLI reusing `absence_ingestion.py` against archived files, no move/archive)
- `create_summary_tables.py:40-301` (map_teams guard, joins, aggregation)
- `dk_matching.py:10-95` (shared DK load + fuzzy match ≥90); `export_slate_averages_vw.py:27-185` (view DROP/CREATE)
- `daily_player_upload.py:34-71` / `daily_fantasy_log_upload.py:41-78` (`ensure_unique_index` + `initialize_database`); `create_log_indexes.py` (offseason backfill)
- `check_ingest_duplicates.py:1-70` (docstring describing the dedup bug + safety net)
- `seed_map_teams.py` (map_teams create/populate), `paths.py` (`resolve_base_data_path`)
- `config.py:7` (no-fallback `G:` download path)
