# TESTING

## Framework & How to Run

- **pytest** (`>=7.4`, `requirements-dev.txt` — separate from runtime deps).
- Config: `pytest.ini` → `pythonpath = .` (so root modules import under a bare `pytest`), `testpaths = tests`.
- Verified current state: **`python -m pytest -q` → 13 passed in ~1s** (run 2026-06-17).

```bash
pip install -r requirements-dev.txt
python -m pytest -q                                       # full suite
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
├── test_daily_player_upload.py       # 3 tests — ingestion behavior
└── test_check_ingest_duplicates.py   # 10 tests — dedup detection/removal
```

## What Is Covered

- **`test_daily_player_upload.py`** (3 tests): single-file ingest loads all logs and learns distinct players; `PLAYER_NAME_MAP` standardization is applied at ingest; re-running with an identical file inserts no duplicates (DB-snapshot dedup).
- **`test_check_ingest_duplicates.py`** (10 tests): stat counting (`total`/`distinct_games`/`distinct_full_rows`); report-only exits non-zero and leaves the DB + no backup; `--remove` dedupes both tables and writes exactly one backup; no-op on a clean DB; `--table` filter touches only the named table; non-exact duplicates warn and keep the earliest (MIN rowid) row; missing DB returns non-zero; `--vacuum` path runs without error.

## Strategy / Patterns

- **Env-seam isolation (no mocking of the DB).** Tests point scripts at a throwaway dir via the `BIGDATABALL_DATA_DIR` env var, then **fresh-import** the module so its module-level path/engine code re-runs against the temp dir. Real SQLite files are created under `tmp_path` — no DB calls are mocked.
  - `tests/conftest.py` `player_upload` fixture: `monkeypatch.setenv` → `sys.modules.pop` → `importlib.import_module`. The docstring explicitly warns **not** to also `importlib.reload` (would double-run module init / create the engine twice). On teardown it calls `module.engine.dispose()` so Windows can delete the locked SQLite file before `tmp_path` cleanup.
  - `test_check_ingest_duplicates.py` defines its own equivalent `dedup_tool` fixture and seeds tables directly with raw `sqlite3`.
- **CLI tests** drive `main()` by `monkeypatch.setattr(sys, "argv", [...])` and assert on the integer exit code + post-state row counts + presence of `.bak-*` backup files.
- **Synthetic inputs:** `tests/helpers.py` `write_player_xlsx` / `make_rows` build `.xlsx` files matching the header layout `daily_player_upload` expects (header on row 0).

## Gaps / Not Covered

- **No tests** for `daily_fantasy_log_upload.py` (the orchestrator + the inline fantasy-log loop), `create_summary_tables.py`, the three `export_*` scripts, `drive_ingestion.py`/`auth_manager.py` (Google Drive), `email_notifier.py`, or `run_db_patch.py`/`verify_db_patch.py`.
- No coverage measurement configured (no `coverage`/`pytest-cov`).
- No integration test of the full pipeline end-to-end; external services (Drive, Gmail, DraftKings CSV) are never exercised — confirmed by `plans/README.md` "What was NOT audited".
- **Broadening coverage to the export/summary/orchestrator scripts is a near-term goal** (maintainer, 2026-06-17). The existing `player_upload` env-seam fixture pattern (fresh import under `BIGDATABALL_DATA_DIR`, dispose engine on teardown) is the template to extend; the summary/export scripts will additionally need a seeded `map_teams` table and the player-average views in place.

## Evidence

- `pytest.ini:1-3`
- `tests/conftest.py:7-27` (fixture, dispose-on-teardown)
- `tests/helpers.py:4-16`
- `tests/test_daily_player_upload.py:12-54` (3 tests)
- `tests/test_check_ingest_duplicates.py:9-201` (10 tests, `dedup_tool` fixture)
- `.github/workflows/test.yml:25-26`
- Local run: `python -m pytest -q` → `13 passed in 0.98s`
