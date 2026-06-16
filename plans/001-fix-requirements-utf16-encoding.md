# Plan 001: `requirements.txt` parses as UTF-8 so `pip install -r requirements.txt` works

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5576703..HEAD -- requirements.txt`
> If `requirements.txt` changed since this plan was written, compare the
> "Current state" facts against the live file before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `5576703`, 2026-06-16

## Why this matters

`requirements.txt` is encoded as UTF-16 (little-endian, with a BOM). `pip` expects
UTF-8. On a clean machine, `pip install -r requirements.txt` either fails to parse
the file or misreads it (it appears to have null bytes between every character when
read as UTF-8). This breaks first-time setup — the single most important onboarding
command in the repo. `CLAUDE.md` documents the problem as a known gotcha; this plan
removes the gotcha by re-encoding the file as UTF-8.

## Current state

- `requirements.txt` (repo root) — the dependency manifest. `file requirements.txt`
  reports: `Unicode text, UTF-16, little-endian text, with CRLF line terminators`.
- The intended content (the actual package list, which must be preserved exactly) is:

```
cachetools==6.2.4
certifi==2025.11.12
charset-normalizer==3.4.4
et_xmlfile==2.0.0
google-api-core==2.28.1
google-api-python-client==2.187.0
google-auth==2.41.1
google-auth-httplib2==0.3.0
google-auth-oauthlib==1.2.3
googleapis-common-protos==1.72.0
greenlet==3.2.4
httplib2==0.31.0
idna==3.11
numpy==2.3.5
oauthlib==3.3.1
openpyxl==3.1.5
pandas==2.3.3
proto-plus==1.27.0
protobuf==6.33.2
pyasn1==0.6.1
pyasn1_modules==0.4.2
pyparsing==3.3.1
python-dateutil==2.9.0.post0
python-dotenv==1.2.1
pytz==2025.2
RapidFuzz==3.14.3
requests==2.32.5
requests-oauthlib==2.0.0
rsa==4.9.1
six==1.17.0
SQLAlchemy==2.0.44
thefuzz==0.22.1
typing_extensions==4.15.0
tzdata==2025.2
uritemplate==4.2.0
urllib3==2.6.2
```

- `CLAUDE.md` contains a note about this encoding (search for "UTF-16"). After this
  plan, that note is stale but harmless; updating it is **out of scope** (see Scope).

## Commands you will need

| Purpose            | Command                                             | Expected on success                          |
|--------------------|-----------------------------------------------------|----------------------------------------------|
| Inspect encoding   | `file requirements.txt`                             | reports `ASCII text` or `UTF-8` (not UTF-16) |
| Verify content     | `cat requirements.txt`                              | the package list above, no stray characters  |
| Count packages     | `grep -c '==' requirements.txt`                     | `37`                                          |

## Scope

**In scope** (the only file you should modify):
- `requirements.txt`

**Out of scope** (do NOT touch):
- `CLAUDE.md` — the stale UTF-16 note is harmless; a separate change owns it.
- Any version pin in the list — do **not** upgrade, add, or remove packages. This
  is an encoding-only change; the bytes that represent each line must be identical
  except for the encoding.

## Git workflow

- Branch: work on the current branch (`claude/improve-hgtf9i`) unless instructed otherwise.
- Single commit; message style matches the repo's plain imperative log
  (e.g. `Re-encode requirements.txt as UTF-8`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Re-encode the file as UTF-8 with LF line endings

Convert the existing UTF-16 file to UTF-8 with a portable Python one-liner. This works
on Linux, macOS, and Windows (unlike `iconv`/`sed -i`, which vary by platform): Python's
`utf-16` decoder consumes the BOM, and we normalize CRLF to LF and write UTF-8 with no
BOM:

```
python3 -c "import pathlib; p = pathlib.Path('requirements.txt'); p.write_text(p.read_text(encoding='utf-16').replace('\r\n', '\n'), encoding='utf-8')"
```

Do **not** retype the package list by hand — convert the existing file so no pin is
accidentally changed.

(If you prefer shell tools and they're available, `iconv -f UTF-16 -t UTF-8 requirements.txt | tr -d '\r' > out && mv out requirements.txt` is an alternative, but the Python one-liner above is the recommended portable approach.)

**Verify**:
- `file requirements.txt` → output contains `ASCII text` or `UTF-8 Unicode text`, and
  does **not** contain `UTF-16`.
- `grep -c '==' requirements.txt` → `37`
- `head -1 requirements.txt` → `cachetools==6.2.4` (no leading garbage bytes)

### Step 2: Confirm pip can parse it

`pip` has a dry-run/parse path that does not need network and does not install:

```
python3 -m pip install --dry-run -r requirements.txt
```

If `--dry-run` is unsupported in this environment, fall back to a parse-only check:

```
python3 -c "import pathlib; [print(l) for l in pathlib.Path('requirements.txt').read_text(encoding='utf-8').splitlines() if l.strip()]"
```

**Verify**: the command reads the file as UTF-8 without a `UnicodeDecodeError` and
prints the 37 package lines. (A network failure during `--dry-run` resolution is
acceptable — the goal is only that the file *parses*; a `UnicodeError` or "null bytes"
error is a failure.)

## Test plan

No automated test is added for this plan (it is an encoding fix to a non-Python file).
Verification is the `file` + `grep -c` + parse check in Steps 1–2.

## Done criteria

ALL must hold:

- [ ] `file requirements.txt` does not report `UTF-16`.
- [ ] `grep -c '==' requirements.txt` returns `37`.
- [ ] `python3 -c "open('requirements.txt', encoding='utf-8').read()"` exits 0 (no decode error).
- [ ] `git diff --stat` shows only `requirements.txt` changed.
- [ ] `plans/README.md` status row for 001 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- The package count after conversion is not 37, or any pinned version differs from the
  list in "Current state" (the conversion corrupted content).
- The Python one-liner fails (e.g. the file is not valid UTF-16) and you cannot
  otherwise convert the file without retyping it.
- `file requirements.txt` already reports UTF-8/ASCII before you start (the file was
  fixed by another change — drift; report and stop).

## Maintenance notes

- After this lands, the "UTF-16 encoded" note in `CLAUDE.md` is stale. A reviewer may
  want to delete that paragraph in a follow-up (intentionally deferred here to keep this
  change single-file and trivially reviewable).
- To prevent regression, consider adding `*.txt text` normalization or an `.editorconfig`
  in a later change so editors don't re-save as UTF-16. Not required for this plan.
