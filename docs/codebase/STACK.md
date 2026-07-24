# STACK

## Language & Runtime

- **Language:** Python. Local development uses **3.13.3** (the git-ignored `venv/`); CI pins **3.11** (`.github/workflows/test.yml:18`). No `python_requires` is declared in-repo, so there is no enforced floor — code must remain compatible across 3.11–3.13.
- **Platform:** Primary development/runtime environment is Windows 11 (paths like `G:\My Drive\...` are hardcoded; see `config.py:7`). CI runs on `ubuntu-latest` (`.github/workflows/test.yml:10`).
- **Project type:** Installable `bigdataball` package (src layout, `src/bigdataball/`) of standalone scripts. No web service, no app, not published to PyPI. Every module is importable from the package and runnable via `python -m bigdataball.<module>` (each has an `if __name__ == "__main__"` guard).

## Dependency Management

- Runtime deps: `requirements.txt` (fully pinned, `==`).
- Dev/test deps: `requirements-dev.txt` (`pytest>=7.4` only).
- No `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, or `poetry.lock` — pip + requirements files only.

## Runtime Dependencies (`requirements.txt`)

Fully pinned. Key direct dependencies (the rest are transitive):

| Package | Version | Role |
|---------|---------|------|
| `pandas` | 2.3.3 | DataFrame ETL — read Excel/CSV, transform, `to_sql`/`read_sql` |
| `numpy` | 2.3.5 | Vectorized calcs in `create_summary_tables.py` (`np.select`, `np.where`) |
| `SQLAlchemy` | 2.0.44 | Engine/`text()` DB access in most scripts |
| `openpyxl` | 3.1.5 | Excel `.xlsx` reading engine for pandas |
| `thefuzz` | 0.22.1 | Fuzzy player-name matching (DraftKings → DB) |
| `RapidFuzz` | 3.14.3 | Fast backend used by `thefuzz` |
| `google-api-python-client` | 2.187.0 | Google Drive API (file list/download) |
| `google-auth-oauthlib` | 1.2.3 | 3-legged OAuth installed-app flow |
| `google-auth` / `google-auth-httplib2` | 2.41.1 / 0.3.0 | Google auth + transport |
| `python-dotenv` | 1.2.1 | Loads `.env` into `config.py` |
| `requests` | 2.32.5 | HTTP (transitive use via google libs / general) |

Standard-library modules used directly: `sqlite3` (raw access in `check_ingest_duplicates.py`, `run_db_patch.py`, `verify_db_patch.py`, `create_log_indexes.py`), `smtplib` + `email.message` (`email_notifier.py`), `argparse`, `glob`, `os`, `io`, `datetime`.

## Dev / Test Tooling

- **pytest** (`>=7.4`, `requirements-dev.txt`) — only declared dev tool.
- `pytest.ini` sets `pythonpath = src` and `testpaths = tests`.

## Linting / Formatting

- **Ruff** is used for linting and formatting via the **VS Code Ruff extension** (editor-side, not a committed config). The repo's `pyproject.toml` is a setuptools packaging manifest only — it has no `[tool.ruff]` section (and there is no `ruff.toml`), so Ruff runs with its default ruleset and formatter. CI does **not** run Ruff — it's a local-editor convention only. The consistent double-quoting and Black-compatible layout in the code reflect the Ruff formatter defaults.

## Evidence

- `requirements.txt` (full pinned dependency list)
- `requirements-dev.txt` (`pytest>=7.4`)
- `pytest.ini` (pythonpath/testpaths)
- `.github/workflows/test.yml` (Python 3.11, ubuntu-latest, install + pytest)
- `config.py:7` (hardcoded Windows `G:` path)
- `check_ingest_duplicates.py:72-76` (stdlib `sqlite3`/`argparse` imports)
- `email_notifier.py:1-2` (`smtplib`, `email.message`)
- Absence of `pyproject.toml`/`setup.py` confirmed by directory scan (`docs/codebase/.codebase-scan.txt`)
- Python 3.13.3 (local `venv/`), Ruff-via-VS-Code-extension: confirmed by maintainer (2026-06-17)
