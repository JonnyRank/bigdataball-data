# TESTING

## Framework & How to Run

- **pytest** (`>=7.4`, `requirements-dev.txt` — separate from runtime deps).
- Config: `pytest.ini` → `pythonpath = src` (so modules import under the `bigdataball` package), `testpaths = tests`.
- Verified current state: **`python -m pytest -q` → 68 passed** (re-run 2026-07-25 on `443ac89`).

```bash
pip install -r requirements-dev.txt
python -m pytest -q                                       # full suite (68 tests)
python -m pytest -q tests/test_check_ingest_duplicates.py # one file
python -m pytest -q -k dedup                              # by keyword
```

- **CI:** `.github/workflows/test.yml` runs `python -m pytest -q` on every push to `main` and every PR (ubuntu-latest, Python 3.13, after `pip install -e .`).

## Organization

```text
tests/
├── __init__.py                       # makes `from tests.helpers import ...` work
├── conftest.py                       # `player_upload` + `fantasy_upload` fixtures
├── helpers.py                        # synthetic .xlsx writers
├── test_absence_ingestion.py         # 11 — DNP-DND-NWT sheet → player_absences
├── test_check_ingest_duplicates.py   # 10 — dedup detection/removal
├── test_daily_fantasy_log_upload.py  # 10 — fantasy-log ingestion (inline loop)
├── test_seed_map_teams.py            # 9  — map_teams seeding
├── test_dk_matching.py               # 8  — DraftKings load + fuzzy match helper
├── test_daily_player_upload.py       # 6  — box-score ingestion behavior
├── test_create_summary_tables.py     # 5  — fantasy_averages aggregation + views
├── test_seasons.py                   # 3  — season-filter constants/SQL
├── test_patch_fantasy_id_types.py    # 3  — one-time FLOAT→INTEGER ID migration
├── test_paths.py                     # 2  — resolve_base_data_path precedence
└── test_orchestrator_warnings.py     # 1  — unmatched-players worklist warning
```

Eleven modules, **68 tests** total (counts verified 2026-07-25).

## What Is Covered

- **`test_daily_player_upload.py`** (6): single-file ingest loads all logs and learns distinct players; `PLAYER_NAME_MAP` standardization at ingest; re-running an identical file inserts no duplicates (DB-snapshot dedup); plus column/rename and unique-index behavior.
- **`test_daily_fantasy_log_upload.py`** (10): single-file fantasy-log load + player learning, name standardization, `DRAFTKINGS1` column drop/rename, ISO date handling (plan 010), plus the plan-014 ID-typing paths — fractional-ID rejection and the missing-ID drop path (drop counted and surfaced in the email). Uses a module-scoped `autouse` fixture that no-ops `email_notifier.send_email_alert` so `main()`-driving tests don't attempt a real SMTP send.
- **`test_absence_ingestion.py`** (11): parsing the `DNP-DND-NWT` sheet into `player_absences`, `ABSENCE_TYPE` derivation, the box-score-wins conflict filter on `(PLAYER_ID, DATE)`, `dim_players` learning, and the UNIQUE-index backstop.
- **`test_check_ingest_duplicates.py`** (10): stat counting; report-only exits non-zero and leaves the DB + no backup; `--remove` dedupes and writes exactly one backup; no-op on a clean DB; `--table` filter; non-exact duplicates warn and keep the earliest (MIN rowid) row; missing DB returns non-zero; `--vacuum` path runs without error.
- **`test_dk_matching.py`** (8): DKEntries.csv header detection, `PLAYER_NAME_MAP` application, `thefuzz` match at the ≥90 threshold, `to_sql_in_list` escaping (plan 006 helper).
- **`test_seed_map_teams.py`** (9): `map_teams` create/populate, `BIGDATABALL_SEED_FORCE` overwrite behavior, deriving `RAW_TEAM_NAME` from real `fantasy_logs.TEAM` values (plan 008).
- **`test_create_summary_tables.py`** (5): the missing-tables guard, basic aggregation (GP/FPPG/SEASON/TEAM/canonical PLAYER), Regular-vs-Playoffs `SEASON_TYPE` + `SEASON_KEY` format, the L30FPPM 30-day window vs all-games FPPM, and `run_summary_pipeline` view creation (plan 011).
- **`test_patch_fantasy_id_types.py`** (3): the one-time `fantasy_logs` FLOAT→INTEGER migration — column-affinity flip (including a real `GAME_ID` column), data/index preservation, idempotency, and fractional-ID rejection (plan 014).
- **`test_seasons.py`** (3) / **`test_paths.py`** (2): season-filter constants + `slate_seasons_sql()`; `resolve_base_data_path()` env/mount/local precedence.
- **`test_orchestrator_warnings.py`** (1): the regular-season unmatched-players worklist warning (plan 004).

## Strategy / Patterns

- **Env-seam isolation (no mocking of the DB).** Tests point scripts at a throwaway dir via the `BIGDATABALL_DATA_DIR` env var, then **fresh-import** the module so its module-level path/engine code re-runs against the temp dir. Real SQLite files are created under `tmp_path` — no DB calls are mocked.
  - `tests/conftest.py` defines **two** such fixtures, one per ingestion path:
    - `player_upload` (`tests/conftest.py:83-103`) — `monkeypatch.setenv` → `sys.modules.pop` → `importlib.import_module` for `daily_player_upload`. The docstring explicitly warns **not** to also `importlib.reload` (would double-run module init / create the engine twice).
    - `fantasy_upload` (`tests/conftest.py:32-80`) — the same seam for the orchestrator `daily_fantasy_log_upload`, which additionally needs the whole `_FANTASY_DEPS` chain popped and the Google API modules (`googleapiclient`, `google.oauth2`, `google_auth_oauthlib`) injected as stub modules so the import doesn't need network or credentials. It also wraps `email_notifier.send_email_alert` so that any email escaping a test is subject-prefixed `[PYTEST]` — a safety net for the case where the developer's `.env` has email enabled. Tests that want no email at all still monkeypatch the sender themselves, which replaces the wrapper.
  - Both fixtures call `module.engine.dispose()` on teardown so Windows can delete the locked SQLite file before `tmp_path` cleanup, and pop their modules back out of `sys.modules`.
  - `test_check_ingest_duplicates.py` defines its own equivalent `dedup_tool` fixture and seeds tables directly with raw `sqlite3`.
- **CLI tests** drive `main()` by `monkeypatch.setattr(sys, "argv", [...])` and assert on the integer exit code + post-state row counts + presence of `.bak-*` backup files.
- **Synthetic inputs:** `tests/helpers.py` `write_player_xlsx` / `make_rows` build `.xlsx` files matching the header layout `daily_player_upload` expects (header on row 0).

## Gaps / Not Covered

- **The inline fantasy-log loop is now covered** (`test_daily_fantasy_log_upload.py`, plan 010), but the **end-to-end orchestrator** (`main()`'s full stage sequence) is not driven as a whole.
- **No tests** for the view-building bodies of the three `export_*` scripts (their DK-matching helper *is* tested via `test_dk_matching.py`) — this is the one remaining planned gap, `plans/019-test-export-view-builders.md` (TODO). Also untested: `drive_ingestion.py`/`auth_manager.py` (Google Drive), `email_notifier.py`, and `run_db_patch.py`/`verify_db_patch.py`. `create_summary_tables.py` is now covered (plan 011 DONE).
- No coverage measurement configured (no `coverage`/`pytest-cov`).
- No integration test of the full pipeline end-to-end; external services (Drive, Gmail, DraftKings CSV) are never exercised — confirmed by `plans/README.md` "What was NOT audited".
- **Broadening coverage to the export view-builders stays a near-term goal** (plan 019). The `player_upload` env-seam fixture pattern (fresh import under `BIGDATABALL_DATA_DIR`, dispose engine on teardown) is the template to extend, and `test_create_summary_tables.py` (plan 011) is the worked example of applying it to a downstream stage; the export scripts additionally need a seeded `map_teams` table (easy via `seed_map_teams.py`), the player-average views in place, and a stand-in for the `~/Downloads/DKEntries.csv` slate input.

## Evidence

- `pytest.ini:1-3`
- `tests/conftest.py:7-29` (dep list + service stubs), `:32-80` (`fantasy_upload`), `:83-103` (`player_upload`, dispose-on-teardown)
- `tests/helpers.py` (synthetic `.xlsx` writers, incl. `write_fantasy_xlsx`)
- `tests/test_*.py` — eleven modules (per-file counts above)
- `tests/test_check_ingest_duplicates.py` (10 tests, `dedup_tool` fixture)
- `.github/workflows/test.yml:29-30`
- Local run: `python -m pytest -q` → `68 passed` (2026-07-25 on `443ac89`)
