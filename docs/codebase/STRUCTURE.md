# STRUCTURE

## Layout

Flat layout — all Python modules live at the repo root (no `src/` package). A `src/bigdataball/` refactor is *planned* (`plans/009-flat-to-src-layout.md`) but **not yet executed**: commit `90bc0ab` titled "Convert flat layout to src/bigdataball/ package" only added the plan document. See `CONCERNS.md` (Intent vs. Reality).

```
bigdataball-data/
├── daily_fantasy_log_upload.py     # MAIN orchestrator (despite the name)
├── daily_player_upload.py          # ingest player box-score logs
├── drive_ingestion.py              # download latest .xlsx from Google Drive
├── auth_manager.py                 # 3-legged Google OAuth helper
├── config.py                       # paths, Drive job defs, email settings (loads .env)
├── mappings.py                     # PLAYER_NAME_MAP (variant → canonical name)
├── create_summary_tables.py        # build fantasy_averages + player-average views
├── export_slate_averages_vw.py     # build vw_daily_slate / vw_daily_slate_l30
├── export_playoffs_slate_averages_vw.py  # build vw_daily_slate_playoffs
├── export_slate_averages_csv.py    # export slate averages to timestamped CSV
├── email_notifier.py               # SMTP success/error notification
├── check_ingest_duplicates.py      # report/remove duplicate (PLAYER_ID, DATE) rows
├── run_db_patch.py                 # one-time retroactive player-name fix
├── verify_db_patch.py              # verify the name patch
├── requirements.txt / requirements-dev.txt
├── pytest.ini
├── CLAUDE.md                       # primary project guidance
├── tests/                          # pytest suite
│   ├── __init__.py
│   ├── conftest.py                 # `player_upload` fixture (env-seam fresh import)
│   ├── helpers.py                  # synthetic .xlsx writers
│   ├── test_daily_player_upload.py
│   └── test_check_ingest_duplicates.py
├── plans/                          # improve-skill handoff plans (001–009 + README index)
├── docs/codebase/                  # (this documentation)
├── *.sql                           # standalone/manual SQL (git-ignored via *.sql)
├── Data/                           # local fallback data dir (DB + archive folders)
├── .github/                        # CI workflows, Copilot instructions, agents/skills
└── .claude/                        # skills + ephemeral worktrees (git-ignored)
```

## Entry Points

All scripts are runnable directly (`python <script>.py`) and importable. There is **no** `main.py`, console-script, or manifest `scripts` entry — the scan reports "No common entry points found".

| Entry point | Role |
|-------------|------|
| `daily_fantasy_log_upload.py` `main()` | **Primary orchestrator.** Runs the full pipeline: Drive ingestion → player upload → fantasy upload → summary tables → slate views (regular + playoffs) → CSV export → email. |
| `daily_player_upload.py` `main()` | Player box-score ingestion (called by orchestrator; returns `(processed, overwritten)`). |
| `drive_ingestion.py` `main()` | Downloads latest matched `.xlsx` from each configured Drive folder. |
| `create_summary_tables.py` `run_summary_pipeline()` | Rebuilds `fantasy_averages` + convenience views + CSVs. |
| `export_slate_averages_vw.py` `run_slate_averages_pipeline()` | Builds `vw_daily_slate`, `vw_daily_slate_l30`. Returns unmatched DK names. |
| `export_playoffs_slate_averages_vw.py` `run_playoffs_slate_averages_pipeline()` | Builds `vw_daily_slate_playoffs`. |
| `export_slate_averages_csv.py` `run_slate_averages_smart_export()` | Exports slate averages to timestamped CSVs in `csv_exports/`. |
| `check_ingest_duplicates.py` `main()` | CLI (`--remove`, `--table`, `--vacuum`); exits non-zero when duplicates exist. |
| `run_db_patch.py` / `verify_db_patch.py` | One-time retroactive name fix + verification. |

## Key Files

- **`config.py`** — single config module: `BASE_DOWNLOAD_DIR` (hardcoded `G:` path, no fallback), `DATASET_JOBS` (Drive folder IDs from env + filename match substrings), credential filenames, OAuth scopes, email settings.
- **`mappings.py`** — `PLAYER_NAME_MAP` dict, the single source of truth for name standardization.
- **`CLAUDE.md`** — the most authoritative human-written description of architecture and conventions (more current than the README/setup guide).
- **`plans/README.md`** — index of the nine improve-skill plans with execution status (001–003 DONE, 004–009 TODO).

## Data Directories (under the resolved base path, git-ignored)

- `Data/nba_fantasy_logs.db` — the SQLite DB (~36 MB; git-ignored via `*.db`).
- `Data/Daily_Fantasy_Logs/`, `Data/Daily_Player_Logs/` — input drop folders (downloaded from Drive).
- `Data/Archived_Fantasy_Logs/`, `Data/Archived_Player_Logs/` — processed-file archives.
- `csv_exports/`, `todo_mappings.txt` — created on demand under the base path.

## Evidence

- `docs/codebase/.codebase-scan.txt` (directory tree, "No common entry points found")
- `daily_fantasy_log_upload.py:69-399` (`main()` orchestration order)
- `daily_player_upload.py:61-266` (`main()` returns `(processed, overwritten)`)
- `config.py:1-36`
- `mappings.py:5-17`
- `plans/README.md:13-22` (plan statuses)
- `tests/` directory (conftest, helpers, two test files)
- `.gitignore:19-31` (`*.db`, `*.sql` ignored)
