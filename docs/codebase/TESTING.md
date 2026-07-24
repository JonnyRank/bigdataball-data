# TESTING

## Framework & How to Run

- **pytest** (`>=7.4`, `requirements-dev.txt` — separate from runtime deps).
- Config: `pytest.ini` → `pythonpath = src` (so modules import under the `bigdataball` package), `testpaths = tests`.
- Verified current state: **`python -m pytest -q` → 56 passed in ~9s** (run 2026-07-23).

```bash
pip install -r requirements-dev.txt
python -m pytest -q                                       # full suite (56 tests)
python -m pytest -q tests/test_check_ingest_duplicates.py # one file
python -m pytest -q -k dedup                              # by keyword
```

- **CI:** `.github/workflows/test.yml` runs `python -m pytest -q` on every push to `main` and every PR (ubuntu-latest, Python 3.11).

## Organization

```
tests/
├── __init__.py                       # makes `from tests.helpers import ...` work
├── conftest.py                       # `player_upload` fixture
├── helpers.py                        # synthetic .xlsx writers
├── test_daily_player_upload.py       # 6  — box-score ingestion behavior
├── test_daily_fantasy_log_upload.py  # 6  — fantasy-log ingestion (inline loop)
├── test_absence_ingestion.py         # 11 — DNP-DND-NWT sheet → player_absences
├── test_check_ingest_duplicates.py   # 10 — dedup detection/removal
├── test_dk_matching.py               # 8  — DraftKings load + fuzzy match helper
├── test_seed_map_teams.py            # 9  — map_teams seeding
├── test_seasons.py                   # 3  — season-filter constants/SQL
├── test_paths.py                     # 2  — resolve_base_data_path precedence
└── test_orchestrator_warnings.py     # 1  — unmatched-players worklist warning
```

## What Is Covered

- **`test_daily_player_upload.py`** (6): single-file ingest loads all logs and learns distinct players; `PLAYER_NAME_MAP` standardization at ingest; re-running an identical file inserts no duplicates (DB-snapshot dedup); plus column/rename and unique-index behavior.
- **`test_daily_fantasy_log_upload.py`** (6): single-file fantasy-log load + player learning, name standardization, `DRAFTKINGS1` column drop/rename, ISO date handling (plan 010). Uses a module-scoped `autouse` fixture that no-ops `email_notifier.send_email_alert` so `main()`-driving tests don't attempt a real SMTP send.
- **`test_absence_ingestion.py`** (11): parsing the `DNP-DND-NWT` sheet into `player_absences`, `ABSENCE_TYPE` derivation, the box-score-wins conflict filter on `(PLAYER_ID, DATE)`, `dim_players` learning, and the UNIQUE-index backstop.
- **`test_check_ingest_duplicates.py`** (10): stat counting; report-only exits non-zero and leaves the DB + no backup; `--remove` dedupes and writes exactly one backup; no-op on a clean DB; `--table` filter; non-exact duplicates warn and keep the earliest (MIN rowid) row; missing DB returns non-zero; `--vacuum` path runs without error.
- **`test_dk_matching.py`** (8): DKEntries.csv header detection, `PLAYER_NAME_MAP` application, `thefuzz` match at the ≥90 threshold, `to_sql_in_list` escaping (plan 006 helper).
- **`test_seed_map_teams.py`** (9): `map_teams` create/populate, `BIGDATABALL_SEED_FORCE` overwrite behavior, deriving `RAW_TEAM_NAME` from real `fantasy_logs.TEAM` values (plan 008).
- **`test_seasons.py`** (3) / **`test_paths.py`** (2): season-filter constants + `slate_seasons_sql()`; `resolve_base_data_path()` env/mount/local precedence.
- **`test_orchestrator_warnings.py`** (1): the regular-season unmatched-players worklist warning (plan 004).

## Strategy / Patterns

- **Env-seam isolation (no mocking of the DB).** Tests point scripts at a throwaway dir via the `BIGDATABALL_DATA_DIR` env var, then **fresh-import** the module so its module-level path/engine code re-runs against the temp dir. Real SQLite files are created under `tmp_path` — no DB calls are mocked.
  - `tests/conftest.py` `player_upload` fixture: `monkeypatch.setenv` → `sys.modules.pop` → `importlib.import_module`. The docstring explicitly warns **not** to also `importlib.reload` (would double-run module init / create the engine twice). On teardown it calls `module.engine.dispose()` so Windows can delete the locked SQLite file before `tmp_path` cleanup.
  - `test_check_ingest_duplicates.py` defines its own equivalent `dedup_tool` fixture and seeds tables directly with raw `sqlite3`.
- **CLI tests** drive `main()` by `monkeypatch.setattr(sys, "argv", [...])` and assert on the integer exit code + post-state row counts + presence of `.bak-*` backup files.
- **Synthetic inputs:** `tests/helpers.py` `write_player_xlsx` / `make_rows` build `.xlsx` files matching the header layout `daily_player_upload` expects (header on row 0).

## Gaps / Not Covered

- **The inline fantasy-log loop is now covered** (`test_daily_fantasy_log_upload.py`, plan 010), but the **end-to-end orchestrator** (`main()`'s full stage sequence) is not driven as a whole.
- **No tests** for `create_summary_tables.py` (plan 011, TODO), the view-building bodies of the three `export_*` scripts (their DK-matching helper *is* tested via `test_dk_matching.py`), `drive_ingestion.py`/`auth_manager.py` (Google Drive), `email_notifier.py`, or `run_db_patch.py`/`verify_db_patch.py`.
- No coverage measurement configured (no `coverage`/`pytest-cov`).
- No integration test of the full pipeline end-to-end; external services (Drive, Gmail, DraftKings CSV) are never exercised — confirmed by `plans/README.md` "What was NOT audited".
- **Broadening coverage to the summary/export scripts stays a near-term goal** (plan 011). The `player_upload` env-seam fixture pattern (fresh import under `BIGDATABALL_DATA_DIR`, dispose engine on teardown) is the template to extend; the summary/export scripts additionally need a seeded `map_teams` table (now easy via `seed_map_teams.py`) and the player-average views in place.

## Evidence

- `pytest.ini:1-3`
- `tests/conftest.py:7-27` (fixture, dispose-on-teardown)
- `tests/helpers.py` (synthetic `.xlsx` writers, incl. `write_fantasy_xlsx`)
- `tests/test_*.py` — nine modules (per-file counts above)
- `tests/test_check_ingest_duplicates.py` (10 tests, `dedup_tool` fixture)
- `.github/workflows/test.yml:25-26`
- Local run: `python -m pytest -q` → `56 passed in 8.52s` (2026-07-23)
