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
   │  daily_fantasy_log_upload (inline loop)  # DFS logs → fantasy_logs (+ dim_players)
   ▼
SQLite: player_logs, fantasy_logs, dim_players
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
2. **Ingestion / ETL** — `daily_player_upload.py` and the inline loop in `daily_fantasy_log_upload.py`. Read Excel → sanitize headers → rename → standardize names (`mappings.py`) → dedup → `to_sql(append)`.
3. **Aggregation** — `create_summary_tables.py`: joins logs with `dim_players` + `map_teams`, derives `SEASON_TYPE`/`SEASON_KEY`, aggregates to `fantasy_averages`, builds player-average views.
4. **Slate selection / export** — the three `export_*` scripts: read `~/Downloads/DKEntries.csv`, fuzzy-match DK names to DB, build slate views / CSVs scoped to the current slate.
5. **Maintenance** — `check_ingest_duplicates.py` (dedup safety net), `run_db_patch.py` / `verify_db_patch.py` (retroactive name fixes).
6. **Notification** — `email_notifier.py` (SMTP over SSL).

## Key Architectural Patterns

- **Per-file path resolution (decentralized).** Every DB-touching script independently resolves `BASE_DATA_PATH`. The newer 3-way form: `BIGDATABALL_DATA_DIR` env override → `G:\My Drive\...` if the mount exists → local `Data/` (`daily_fantasy_log_upload.py:29-35`, `daily_player_upload.py:21-27`, `check_ingest_duplicates.py:84-89`). Older scripts use a 2-way form with no env override (`create_summary_tables.py:13-17`, the three `export_*` scripts, `run_db_patch.py:9-13`, `verify_db_patch.py:8-11`). `config.py:7` hardcodes the `G:` path with **no fallback**, so Drive ingestion effectively requires the mount.

- **Resilient stage orchestration.** Each pipeline stage is wrapped in try/except; errors are appended to `pipeline_errors` and the run continues so one failure doesn't abort the rest (`daily_fantasy_log_upload.py:80-347`). The final email reports success or the collected errors.

- **In-memory de-duplication via `log_key`.** Upload scripts build a composite `PLAYER_ID + "_" + DATE` key, load existing `(PLAYER_ID, DATE)` from the DB, skip rows already present, and `.update()` the in-memory key set after each insert. **No DB-level constraint** enforces uniqueness — `player_logs`/`fantasy_logs` are created implicitly by `to_sql(if_exists="append")` with no PK/UNIQUE. `check_ingest_duplicates.py` is the safety net.

- **Two DB access styles coexist.** SQLAlchemy `create_engine`/`text()`/`engine.begin()` + pandas `to_sql`/`read_sql` in the pipeline scripts; raw `sqlite3` in `check_ingest_duplicates.py`, `run_db_patch.py`, `verify_db_patch.py`. Match the file you're editing.

- **Excel column sanitization → semantic rename.** Headers are normalized (newlines/hyphens/spaces → `_`, special chars stripped, UPPERCASED) then a per-script `rename_map` applies semantic names (`daily_player_upload.py:122-161`, `daily_fantasy_log_upload.py:165-204`).

- **Fuzzy DraftKings matching.** Export scripts read `DKEntries.csv`, detect the header row by scanning the first 50 lines for `"Position"` + `"Name + ID"`, apply explicit `PLAYER_NAME_MAP` first, then `thefuzz.process.extractOne` with a **score ≥ 90** threshold; misses are collected as `unmatched_names` (`export_slate_averages_vw.py:37-98`).

- **Views rebuilt by DROP + CREATE in a transaction.** `with engine.begin(): DROP VIEW IF EXISTS; CREATE VIEW` (`create_summary_tables.py:343-345`, export scripts). Player names are escaped (`.replace("'", "''")`) before being interpolated into `IN (...)` lists.

## Database Schema

Tables: `fantasy_logs`, `player_logs` (raw logs, no PK/UNIQUE), `dim_players` (`PLAYER_ID` PK), `fantasy_averages` (rebuilt `if_exists="replace"`), `map_teams` (`RAW_TEAM_NAME` PK → `TEAM_ABBREVIATION`).

Views: `vw_player_averages_regular_season`, `vw_player_averages_playoffs` (built by summary), `vw_daily_slate`, `vw_daily_slate_l30`, `vw_daily_slate_playoffs` (built by exports).

> `map_teams` is **read** by `create_summary_tables.py` but **created by no Python script** — it must already exist (seed SQL is in `create_team_map_table.sql`, which is git-ignored via `*.sql`). `create_summary_tables.py:40-59` guards for it and aborts cleanly if missing. Plan 008 (TODO) addresses seeding it.

## Derived-Data Invalidation

`fantasy_averages` and all averages are recomputed from the full log tables on each run (`if_exists="replace"`). Duplicate log rows therefore inflate every average — after `check_ingest_duplicates.py --remove`, the summary + slate exports must be re-run (`check_ingest_duplicates.py:264-272`).

## Evidence

- `daily_fantasy_log_upload.py:69-395` (orchestration, try/except per stage)
- `daily_player_upload.py:71-244` (dedup `log_key` flow, `to_sql(append)`)
- `create_summary_tables.py:40-301` (table existence guard, joins, aggregation)
- `export_slate_averages_vw.py:37-185` (DK header detect, fuzzy match ≥90, view DROP/CREATE)
- `check_ingest_duplicates.py:1-70` (docstring describing the dedup bug + safety net)
- `create_team_map_table.sql:3-40` (map_teams seed)
- `config.py:7` (no-fallback `G:` path)
