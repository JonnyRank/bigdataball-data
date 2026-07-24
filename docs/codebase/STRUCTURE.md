# STRUCTURE

## Layout

Src layout — all runtime modules live under the installable `src/bigdataball/` package and import each other with package-relative imports (`from . import mappings`). This was the `src/bigdataball/` refactor tracked by `plans/009-flat-to-src-layout.md`, executed 2026-07-24 (the earlier flat layout at the repo root is gone). See `CONCERNS.md` (Intent vs. Reality).

```
bigdataball-data/
├── src/bigdataball/                # the installable package (src layout, plan 009)
│   ├── __init__.py
│   ├── daily_fantasy_log_upload.py     # MAIN orchestrator (despite the name)
│   ├── daily_player_upload.py          # ingest player box-score logs
│   ├── absence_ingestion.py            # shared: DNP-DND-NWT sheet → player_absences (+ learn dim_players)
│   ├── backfill_player_absences.py     # one-shot CLI: backfill player_absences from archived files
│   ├── patch_absence_column_names.py   # one-time: rename player_absences GAME_DATE/PLAYER_NAME → DATE/PLAYER
│   ├── patch_fantasy_id_types.py       # one-time: cast fantasy_logs PLAYER_ID/GAME_ID → INTEGER
│   ├── drive_ingestion.py              # download latest .xlsx from Google Drive
│   ├── auth_manager.py                 # 3-legged Google OAuth helper
│   ├── config.py                       # download dir, Drive job defs, email settings (loads .env)
│   ├── paths.py                        # resolve_base_data_path() — single path-resolution helper
│   ├── mappings.py                     # PLAYER_NAME_MAP (variant → canonical name)
│   ├── seasons.py                      # SLATE_SEASONS / L30_SEASON / PLAYOFFS_SEASON constants
│   ├── dk_matching.py                  # shared DraftKings load + fuzzy-match helper (used by all exports)
│   ├── seed_map_teams.py               # create + populate the map_teams table
│   ├── create_summary_tables.py        # build fantasy_averages + player-average views
│   ├── export_slate_averages_vw.py     # build vw_daily_slate / vw_daily_slate_l30
│   ├── export_playoffs_slate_averages_vw.py  # build vw_daily_slate_playoffs
│   ├── export_slate_averages_csv.py    # export slate averages to timestamped CSV
│   ├── email_notifier.py               # SMTP success/error notification
│   ├── check_ingest_duplicates.py      # report/remove duplicate (PLAYER_ID, DATE) rows
│   ├── create_log_indexes.py           # one-off: backfill UNIQUE (PLAYER_ID, DATE) indexes on log tables
│   ├── run_db_patch.py                 # one-time retroactive player-name fix
│   └── verify_db_patch.py              # verify the name patch
├── pyproject.toml                  # packaging manifest (setuptools, src layout)
├── requirements.txt / requirements-dev.txt
├── pytest.ini                      # pythonpath = src
├── CLAUDE.md                       # primary project guidance
├── tests/                          # pytest suite
│   ├── __init__.py
│   ├── conftest.py                 # `player_upload` fixture (env-seam fresh import)
│   ├── helpers.py                  # synthetic .xlsx writers
│   └── test_*.py                   # 11 test modules, 68 tests (see TESTING.md)
├── plans/                          # improve-skill handoff plans (001–014 + README index)
├── docs/codebase/                  # (this documentation)
├── *.sql                           # standalone/manual SQL (git-ignored via *.sql)
├── Data/                           # local fallback data dir (DB + archive folders)
├── .github/                        # CI workflows, Copilot instructions, agents/skills
└── .claude/                        # skills + ephemeral worktrees (git-ignored)
```

## Entry Points

All modules are importable from the `bigdataball` package and runnable via `python -m bigdataball.<module>` (direct `python src/bigdataball/<module>.py` execution no longer works — the package-relative imports require the `-m` form). There is **no** `main.py` or `[project.scripts]` console-script entry — console scripts were deliberately deferred (`daily_player_upload.main()` returns a tuple, which would corrupt a console-wrapper exit code).

| Entry point | Role |
|-------------|------|
| `daily_fantasy_log_upload.py` `main()` | **Primary orchestrator.** Runs the full pipeline: Drive ingestion → player upload → fantasy upload → summary tables → slate views (regular + playoffs) → CSV export → email. |
| `daily_player_upload.py` `main()` | Player box-score ingestion (called by orchestrator; returns `(processed, overwritten, absences_count)`). Also ingests the `DNP-DND-NWT` absence sheet per file via `absence_ingestion.py`. |
| `backfill_player_absences.py` (CLI) | One-shot backfill of `player_absences` from already-archived player-feed files; reads files in place, does not move/archive them. |
| `drive_ingestion.py` `main()` | Downloads latest matched `.xlsx` from each configured Drive folder. |
| `create_summary_tables.py` `run_summary_pipeline()` | Rebuilds `fantasy_averages` + convenience views + CSVs. |
| `export_slate_averages_vw.py` `run_slate_averages_pipeline()` | Builds `vw_daily_slate`, `vw_daily_slate_l30`. Returns unmatched DK names. |
| `export_playoffs_slate_averages_vw.py` `run_playoffs_slate_averages_pipeline()` | Builds `vw_daily_slate_playoffs`. |
| `export_slate_averages_csv.py` `run_slate_averages_smart_export()` | Exports slate averages to timestamped CSVs in `csv_exports/`. |
| `check_ingest_duplicates.py` `main()` | CLI (`--remove`, `--table`, `--vacuum`); exits non-zero when duplicates exist. |
| `seed_map_teams.py` (CLI) | Creates + populates `map_teams` (`RAW_TEAM_NAME` → `TEAM_ABBREVIATION`). Run once on a fresh DB; `BIGDATABALL_SEED_FORCE=1` overwrites an existing populated table. |
| `create_log_indexes.py` (CLI) | One-off backfill of the UNIQUE `(PLAYER_ID, DATE)` index on all three log tables (`--table` for one). Refuses to index a table that still has duplicates. |
| `run_db_patch.py` / `verify_db_patch.py` | One-time retroactive name fix + verification. |
| `patch_absence_column_names.py` (CLI) | One-time rename of `player_absences` `GAME_DATE`/`PLAYER_NAME` → `DATE`/`PLAYER`. |

## Key Files

- **`config.py`** — Drive-ingestion config module: `BASE_DOWNLOAD_DIR` (hardcoded `G:` path, no fallback), `DATASET_JOBS` (Drive folder IDs from env + filename match substrings), credential filenames, OAuth scopes, email settings. (Data-*path* resolution for the DB lives in `paths.py`, not here.)
- **`paths.py`** — `resolve_base_data_path()`, the single source of truth for the DB base path (`BIGDATABALL_DATA_DIR` env → `G:` mount → local `Data/`). Every DB-touching script imports it (plan 005).
- **`mappings.py`** — `PLAYER_NAME_MAP` dict, the single source of truth for name standardization.
- **`CLAUDE.md`** — the most authoritative human-written description of architecture and conventions (more current than the README/setup guide).
- **`plans/README.md`** — index of the fourteen improve-skill plans with execution status (all 001–014 now DONE — see the table there for the live state).

## Data Directories (under the resolved base path, git-ignored)

- `Data/nba_fantasy_logs.db` — the SQLite DB (~36 MB; git-ignored via `*.db`).
- `Data/Daily_Fantasy_Logs/`, `Data/Daily_Player_Logs/` — input drop folders (downloaded from Drive).
- `Data/Archived_Fantasy_Logs/`, `Data/Archived_Player_Logs/` — processed-file archives.
- `csv_exports/`, `todo_mappings.txt` — created on demand under the base path.

## Evidence

- `docs/codebase/.codebase-scan.txt` (directory tree, "No common entry points found")
- `daily_fantasy_log_upload.py:69-399` (`main()` orchestration order)
- `daily_player_upload.py:74-302` (`main()` returns `(processed, overwritten, absences_count)`)
- `config.py:1-36`, `paths.py` (`resolve_base_data_path`)
- `mappings.py:5-17`
- `plans/README.md` (plan status table — all 001–014 DONE)
- `tests/` directory (conftest, helpers, eleven `test_*.py` modules — 68 tests)
- `.gitignore:19-31` (`*.db`, `*.sql` ignored)
