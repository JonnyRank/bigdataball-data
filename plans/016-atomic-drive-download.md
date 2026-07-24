# Plan 016: Download Drive files atomically so an interrupted transfer isn't ingested as a complete file

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat aef8efa..HEAD -- src/bigdataball/drive_ingestion.py`
> If `drive_ingestion.py` changed since this plan was written, compare the
> "Current state" excerpt against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `aef8efa`, 2026-07-24
- **Issue**: —

## Why this matters

`download_file` streams a Drive file straight to its **final** path
(`Daily_Fantasy_Logs/<name>.xlsx` etc.). If the transfer is interrupted
mid-stream — `downloader.next_chunk()` raises on a dropped connection, the
process is killed, the machine sleeps — a **truncated `.xlsx` is left at the
final path**. On the next run, the function's own guard
(`if os.path.exists(file_path): [Skipping]`) sees that partial file and skips
re-downloading it, so the pipeline permanently uses a corrupt file: pandas
either raises on ingest (and the per-file loop `break`s, stalling the whole
ingestion — `daily_player_upload.py:295-298`) or, worse, reads a partial sheet
and silently ingests incomplete data that inflates/deflates averages. Because
the download half never `close()`s the file handle explicitly either, the
partial write is especially likely to be flushed to disk on some platforms.

The fix is the standard atomic-write pattern: download to a temporary path in
the same directory, and only `os.replace()` it onto the final name after the
transfer completes. A partial download then never occupies the final path, so
the skip-if-exists guard only ever skips genuinely-complete files.

## Current state

- `src/bigdataball/drive_ingestion.py` — Google Drive download. The relevant
  function (`drive_ingestion.py:48-73`):

```python
def download_file(service, file_id, file_name, local_dest):
    """Downloads a file from Drive to the local destination."""

    # Ensure directory exists
    if not os.path.exists(local_dest):
        os.makedirs(local_dest)

    file_path = os.path.join(local_dest, file_name)

    # Check if file already exists to avoid re-downloading
    if os.path.exists(file_path):
        print(f"  [Skipping] {file_name} already exists.")
        return

    print(f"  [Downloading] {file_name}...")
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while done is False:
        status, done = downloader.next_chunk()
        # Optional: Print progress if needed
        # print(f"Download {int(status.progress() * 100)}%.")

    print(f"  [Success] Saved to {file_path}")
```

- `import io` and `import os` are already at the top of the file
  (`drive_ingestion.py:1-2`). No new imports are required (`os.replace` and
  `os.remove` are stdlib).
- The module top also imports `from .auth_manager import authenticate_google_drive`
  and `from . import config`; `main()` (`drive_ingestion.py:76-96`) calls
  `download_file` in a loop over `config.DATASET_JOBS`. That call site does not
  change.
- Repo conventions: print-based logging, double-quoted strings, 4-space indent
  (`docs/codebase/CONVENTIONS.md`). Match them.
- `drive_ingestion.py` has **no tests** (`docs/codebase/TESTING.md` "Gaps" —
  "Google Drive" modules are unexercised). This plan adds a focused unit test
  that fakes the downloader, so it needs neither network nor credentials.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install deps (editable pkg) | `pip install -e . && pip install -r requirements-dev.txt` | exit 0 |
| Run the new test file | `python -m pytest -q tests/test_drive_ingestion.py` | all pass |
| Full suite | `python -m pytest -q` | `71 passed` (68 existing + 3 new) |

## Scope

**In scope** (the only files you should modify/create):
- `src/bigdataball/drive_ingestion.py` (edit `download_file` only)
- `tests/test_drive_ingestion.py` (create)
- `plans/README.md` (status row update only)

**Out of scope** (do NOT touch, even though they look related):
- `find_latest_file`, `get_drive_service`, `main` in the same file — the change
  is confined to `download_file`.
- `auth_manager.py` / `config.py` — auth and job config are unchanged.
- Do NOT change the skip-if-exists behavior's *intent* (still skip a
  fully-downloaded file); only ensure the file at the final path is always
  complete.

## Git workflow

- Branch: `advisor/016-atomic-drive-download` (or the repo's branch-naming
  convention if one is evident from `git log --oneline`).
- Commit message style: match `git log` (short imperative subject, e.g.
  "Download Drive files atomically via a temp path + rename").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Rewrite the download body to write to a temp path and atomically rename

Replace the download body of `download_file` (from `print(f"  [Downloading]...`
through the final `print(f"  [Success]...")`) with a temp-file-then-rename
version. Keep the directory-creation and skip-if-exists guards exactly as they
are. Target shape:

```python
    print(f"  [Downloading] {file_name}...")
    # Download to a temporary sibling path first, then atomically move it onto
    # the final name only after the transfer completes. This prevents a partial
    # file (interrupted next_chunk, killed process) from occupying the final
    # path, where the skip-if-exists guard above would treat it as complete on
    # the next run and ingest a truncated .xlsx.
    tmp_path = file_path + ".part"
    request = service.files().get_media(fileId=file_id)
    try:
        with io.FileIO(tmp_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                # Optional: Print progress if needed
                # print(f"Download {int(status.progress() * 100)}%.")
        # Success: promote the temp file to the final name (atomic on same fs).
        os.replace(tmp_path, file_path)
    except Exception:
        # Clean up the partial download so it can't be mistaken for a complete
        # file, then re-raise so the caller/orchestrator records the failure.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    print(f"  [Success] Saved to {file_path}")
```

Two load-bearing changes vs. the original:

1. `io.FileIO` is now used as a **context manager** (`with ... as fh:`), so the
   handle is always closed — the original never closed `fh` explicitly.
2. On any exception the `.part` file is removed and the error re-raised, so
   `drive_ingestion.main()`'s caller (`daily_fantasy_log_upload.py:92-97`, which
   wraps the whole ingestion in try/except and records `pipeline_errors`) still
   sees the failure — behavior for the error path is preserved, only the partial
   file is no longer left behind.

**Verify**: `python -c "import ast; src=open('src/bigdataball/drive_ingestion.py').read(); ast.parse(src); assert '.part' in src and 'os.replace(tmp_path, file_path)' in src and 'os.remove(tmp_path)' in src; print('OK')"` → prints `OK`

### Step 2: Add unit tests with a fake downloader (no network)

Create `tests/test_drive_ingestion.py`. Fake `MediaIoBaseDownload` so a
"download" writes bytes to the handle, and drive `download_file` directly. Cover:
completed download lands at the final path with no `.part` left; an interrupted
download leaves **no file at the final path** and **no `.part**; an
already-existing final file is skipped without touching it.

```python
import io
import os

import pytest

from bigdataball import drive_ingestion


class _FakeDownloader:
    """Writes `payload` to the handle across chunks, or raises mid-way."""

    def __init__(self, fh, payload=b"xlsxdata", fail_after=None):
        self._fh = fh
        self._payload = payload
        self._fail_after = fail_after
        self._i = 0

    def next_chunk(self):
        if self._fail_after is not None and self._i >= self._fail_after:
            raise RuntimeError("simulated connection drop")
        self._fh.write(self._payload)
        self._i += 1
        return (None, True)  # (status, done)


def _patch_downloader(monkeypatch, **kwargs):
    def _factory(fh, request):
        return _FakeDownloader(fh, **kwargs)

    monkeypatch.setattr(drive_ingestion, "MediaIoBaseDownload", _factory)


class _FakeService:
    """service.files().get_media(fileId=...) -> a dummy request object."""

    def files(self):
        return self

    def get_media(self, fileId=None):
        return object()


def test_completed_download_lands_at_final_path(tmp_path, monkeypatch):
    _patch_downloader(monkeypatch)
    dest = str(tmp_path / "Daily_Fantasy_Logs")
    drive_ingestion.download_file(_FakeService(), "id1", "feed.xlsx", dest)
    final = os.path.join(dest, "feed.xlsx")
    assert os.path.exists(final)
    assert not os.path.exists(final + ".part")
    with open(final, "rb") as f:
        assert f.read() == b"xlsxdata"


def test_interrupted_download_leaves_no_file(tmp_path, monkeypatch):
    _patch_downloader(monkeypatch, fail_after=0)
    dest = str(tmp_path / "Daily_Fantasy_Logs")
    with pytest.raises(RuntimeError):
        drive_ingestion.download_file(_FakeService(), "id1", "feed.xlsx", dest)
    final = os.path.join(dest, "feed.xlsx")
    assert not os.path.exists(final)          # nothing partial at the real name
    assert not os.path.exists(final + ".part")  # temp cleaned up


def test_existing_file_is_skipped(tmp_path, monkeypatch):
    dest = tmp_path / "Daily_Fantasy_Logs"
    dest.mkdir()
    final = dest / "feed.xlsx"
    final.write_bytes(b"original")
    # If the downloader were invoked it would overwrite; assert it is NOT.
    def _boom(fh, request):
        raise AssertionError("download_file should have skipped")

    monkeypatch.setattr(drive_ingestion, "MediaIoBaseDownload", _boom)
    drive_ingestion.download_file(_FakeService(), "id1", "feed.xlsx", str(dest))
    assert final.read_bytes() == b"original"
```

Note on imports: the suite runs with `pythonpath = src` (`pytest.ini`); confirm
the import style against an existing test (e.g. `tests/test_dk_matching.py`) and
match it (`from bigdataball import drive_ingestion`).

**Verify**: `python -m pytest -q tests/test_drive_ingestion.py` → `3 passed`

### Step 3: Confirm the full suite still passes

**Verify**: `python -m pytest -q` → `71 passed` (68 existing + 3 new). If the
count differs, re-check Step 2 before proceeding.

### Step 4: Update the plans index

In `plans/README.md`, add a DONE status row for plan 016 in the "Execution order
& status" table, matching the existing rows' formatting.

## Test plan

- New file `tests/test_drive_ingestion.py`, 3 tests:
  - `test_completed_download_lands_at_final_path` — happy path; final file
    present, no `.part` residue.
  - `test_interrupted_download_leaves_no_file` — the regression this plan fixes:
    a mid-transfer failure leaves neither the final file nor the temp file.
  - `test_existing_file_is_skipped` — the skip-if-exists guard is preserved and
    does not re-download / overwrite.
- Structural pattern: monkeypatch-based unit test using `tmp_path`, like the
  file-writing tests in the suite; no engine/DB fixture needed here.
- Verification: `python -m pytest -q` → all pass, including the 3 new tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "\.part" src/bigdataball/drive_ingestion.py` shows the temp path in use
- [ ] `grep -n "os.replace(tmp_path, file_path)" src/bigdataball/drive_ingestion.py` returns the promote line
- [ ] `grep -n "os.remove(tmp_path)" src/bigdataball/drive_ingestion.py` returns the cleanup line
- [ ] `python -m pytest -q tests/test_drive_ingestion.py` → `3 passed`
- [ ] `python -m pytest -q` → `71 passed`
- [ ] `git status --short` shows only `src/bigdataball/drive_ingestion.py`, `tests/test_drive_ingestion.py`, and `plans/README.md`
- [ ] `plans/README.md` status row for 016 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `download_file` does not match the "Current state" excerpt (it changed since
  this plan was written — e.g. atomic download was already added).
- The full suite is not green at `68 passed` before your changes (drift check
  fails).
- The completed-download test fails because `os.replace` raises a cross-device
  error — that would mean `tmp_path` and the destination are on different
  filesystems, which should not happen since the temp path is a sibling of the
  final path; report it rather than falling back to `shutil.move`.

## Maintenance notes

- The `.part` suffix is a deliberately boring convention. If a future change
  adds a resumable-download feature, the interrupted-download cleanup here must
  be revisited (you may want to *keep* the `.part` file to resume rather than
  delete it).
- Reviewer should confirm the temp path is a **sibling** of the final path (same
  directory `local_dest`), so `os.replace` stays atomic (same filesystem), and
  that the error path still re-raises so the orchestrator records the failure.
- This does not add a network timeout to the download itself (the
  `next_chunk()` HTTP calls). That is a separate, larger hardening (it requires
  configuring the underlying `httplib2`/`google-api-python-client` transport)
  and is intentionally out of scope here — this plan only ensures a *failed*
  download can't masquerade as a complete one.
