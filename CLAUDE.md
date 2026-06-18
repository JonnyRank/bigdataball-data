# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start Here

Use the codebase docs for details instead of re-discovering the repo each time:
- `docs/codebase/STACK.md`
- `docs/codebase/STRUCTURE.md`
- `docs/codebase/ARCHITECTURE.md`
- `docs/codebase/CONVENTIONS.md`
- `docs/codebase/CONCERNS.md`
- `docs/codebase/TESTING.md`
- `docs/codebase/INTEGRATIONS.md`

## What this is

An NBA DFS data pipeline in Python. It downloads player box-score and DraftKings fantasy-log Excel files from Google Drive, loads them into a local SQLite database (`nba_fantasy_logs.db`), and exports per-player averages to SQL views and CSVs consumed by Excel-based DFS analysis. Every entry point is a standalone script.

## Build And Run

```bash
pip install -r requirements.txt          # install deps

python daily_fantasy_log_upload.py       # MAIN orchestrator — runs the full pipeline
```

`daily_fantasy_log_upload.py` is the whole-pipeline orchestrator despite its name. Individual stages can be run standalone:

```bash
python drive_ingestion.py            # download latest .xlsx from Google Drive
python daily_player_upload.py        # ingest player box-score logs only
python create_summary_tables.py      # rebuild fantasy_averages + player-average views
python export_slate_averages_vw.py   # rebuild vw_daily_slate / vw_daily_slate_l30
python export_playoffs_slate_averages_vw.py  # rebuild vw_daily_slate_playoffs
python export_slate_averages_csv.py  # export slate averages to timestamped CSV
python check_ingest_duplicates.py            # report duplicate (PLAYER_ID, DATE) log rows
python check_ingest_duplicates.py --remove   # back up DB, then delete the duplicates
python run_db_patch.py               # one-time retroactive player-name fix
python verify_db_patch.py            # verify the name patch
```

## Architecture

Sequential file-based pipeline — no service, no app. See `docs/codebase/ARCHITECTURE.md` for the full flow diagram, component breakdown, and key patterns (path resolution, dedup, fuzzy matching, view rebuilds). Cross-cutting conventions are in `docs/codebase/CONVENTIONS.md`.

The riskiest files to change: `daily_fantasy_log_upload.py` (orchestrator + inline fantasy-log loop) and `daily_player_upload.py` (ingestion + dedup) — large, high-churn, and partially untested.

## Repo-Specific Pitfalls

- **Season strings are hardcoded** and differ per view — update each at season rollover (see `docs/codebase/CONVENTIONS.md` Hardcoded Season Filters).
- **`map_teams` must pre-exist** — `create_summary_tables.py` reads it but no Python script creates it. Seed from `create_team_map_table.sql` (git-ignored via `*.sql`; see `docs/codebase/ARCHITECTURE.md`) on a fresh DB.
- **Duplicate log rows inflate every average.** After `check_ingest_duplicates.py --remove`, re-run `create_summary_tables.py` and the slate exports.
- **Google Drive auth is interactive** — first run opens a browser; headless runs require a pre-existing valid `token.json`.
- **Path resolution is inconsistent across scripts** — match the idiom already in the file you're editing (see `docs/codebase/ARCHITECTURE.md`).
- **The DB is not committed** — running any pipeline stage requires either the `G:` mount or a local `Data/` dir populated with source `.xlsx` files.

## Testing And Verification

```bash
pip install -r requirements-dev.txt
python -m pytest -q                      # full suite
```

CI runs `pytest -q` on every push/PR. See `docs/codebase/TESTING.md` for coverage details and gaps. Untested scripts (`daily_fantasy_log_upload.py`, summary, exports) are best verified by reading console output and inspecting the DB directly.

## Documentation

When updating project guidance, prefer editing the specific doc in `docs/codebase/` over expanding this file.

When working on a GitHub issue, check if the task is already described in `plans/README.md`. Update the plan status on completion.

`.github/` contains a `sqlite-dba` agent and `sqlite-optimization` skill for inspecting/optimizing the database. `.claude/skills/improve/` holds a codebase-audit playbook.
