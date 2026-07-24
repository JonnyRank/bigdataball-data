# Plan 015: Give the notification email a network timeout so a stalled SMTP send can't hang the daily run

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat aef8efa..HEAD -- src/bigdataball/email_notifier.py`
> If `email_notifier.py` changed since this plan was written, compare the
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

The pipeline's final step sends a success/error email over `smtplib.SMTP_SSL`.
The connection is opened with **no `timeout`**, and the process never calls
`socket.setdefaulttimeout`, so the socket blocks **forever** if Gmail's SMTP
endpoint accepts the TCP/TLS connection but then stalls (a half-open
connection, a network partition, an ISP-level hang). The whole pipeline is run
unattended by Windows Task Scheduler (`docs/codebase/CONCERNS.md:15`), so a hung
send is the worst failure mode: the run never finishes, the SQLAlchemy engine
and DB file stay held open, no notification is delivered (the very step that
hung is the notifier), and the next scheduled run can collide with the still-
running one. Plan 010's own status note in `plans/README.md` records this
concretely: a `main()`-driving test "hangs" because the send "blackholes with no
timeout." A bounded timeout turns an infinite hang into a caught, logged
`Failed to send email notification: ...` line — which the existing `try/except`
already handles gracefully.

## Current state

- `src/bigdataball/email_notifier.py` — the only SMTP code in the repo. The
  whole module (25 lines):

```python
import smtplib
from email.message import EmailMessage
from . import config


def send_email_alert(subject, body):
    """Sends an email notification using settings from config.py."""
    if not getattr(config, "EMAIL_ENABLED", False):
        print("Email notifications are disabled in config.")
        return

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECEIVER

    try:
        # Connect to Gmail's SMTP server using SSL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Notification email sent to {config.EMAIL_RECEIVER}")
    except Exception as e:
        print(f"Failed to send email notification: {e}")
```

- The `except Exception` on line 24 already catches send failures and prints a
  message, so a timeout raising `TimeoutError`/`socket.timeout` is handled the
  same way an auth failure already is — no new error path is needed.
- Repo conventions that apply: print-based logging (no `logging` module
  anywhere — `docs/codebase/CONVENTIONS.md` "Error Handling"); double-quoted
  strings; 4-space indentation. Match them.
- There are currently **no tests** for `email_notifier.py`
  (`docs/codebase/TESTING.md` "Gaps"). This plan adds the first one.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install deps (editable pkg) | `pip install -e . && pip install -r requirements-dev.txt` | exit 0 |
| Run the new test file | `python -m pytest -q tests/test_email_notifier.py` | all pass |
| Full suite | `python -m pytest -q` | `70 passed` (68 existing + 2 new) |

## Scope

**In scope** (the only files you should modify/create):
- `src/bigdataball/email_notifier.py` (edit)
- `tests/test_email_notifier.py` (create)
- `plans/README.md` (status row update only)

**Out of scope** (do NOT touch, even though they look related):
- `src/bigdataball/config.py` — do not change `EMAIL_ENABLED` or add a timeout
  constant there; keep the timeout local to the notifier to keep the change
  minimal and reviewable.
- Any other module that calls `send_email_alert` (the orchestrator) — its
  behavior is unchanged; the function signature stays identical.
- Do NOT introduce the `logging` module or change the print-based style.

## Git workflow

- Branch: `advisor/015-smtp-send-timeout` (or the repo's branch-naming
  convention if one is evident from `git log --oneline`).
- Commit message style: match `git log` (short imperative subject, e.g.
  "Add a network timeout to the notification email send").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a module-level timeout constant and pass it to `SMTP_SSL`

In `src/bigdataball/email_notifier.py`:

1. Add a module-level constant just below the imports:

```python
# Bound the SMTP connection so a stalled Gmail endpoint can't hang the whole
# unattended pipeline forever. On timeout, smtplib raises and the except below
# turns it into a logged, non-fatal "Failed to send" line.
SMTP_TIMEOUT_SECONDS = 30
```

2. Change the connection line to pass the timeout:

```python
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
```

`smtplib.SMTP_SSL` accepts `timeout` as a keyword argument on all supported
Python versions (3.11–3.13). The timeout applies to the initial connect **and**
to each subsequent socket operation (`login`, `send_message`), so it bounds the
entire send, not just the TCP handshake.

**Verify**: `python -c "import ast,sys; src=open('src/bigdataball/email_notifier.py').read(); assert 'timeout=SMTP_TIMEOUT_SECONDS' in src and 'SMTP_TIMEOUT_SECONDS = 30' in src; ast.parse(src); print('OK')"` → prints `OK`

### Step 2: Add a regression test that the timeout is passed through

Create `tests/test_email_notifier.py`. The test must NOT open a real socket —
it monkeypatches `smtplib.SMTP_SSL` with a fake and asserts the `timeout`
keyword is forwarded, and that a raising SMTP is swallowed (not re-raised).

Model the test on the env-seam / monkeypatch style already used in the suite
(e.g. `tests/test_dk_matching.py` for a plain-function test; the
`monkeypatch`/`capsys` fixtures are standard pytest). Use this structure:

```python
import smtplib

from bigdataball import email_notifier


class _FakeSMTP:
    """Records the kwargs SMTP_SSL was called with; no network."""

    last_kwargs = None

    def __init__(self, *args, **kwargs):
        _FakeSMTP.last_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, *a, **k):
        pass

    def send_message(self, *a, **k):
        pass


def test_send_passes_timeout(monkeypatch):
    monkeypatch.setattr(email_notifier.config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(email_notifier.config, "EMAIL_SENDER", "s@example.com")
    monkeypatch.setattr(email_notifier.config, "EMAIL_PASSWORD", "pw")
    monkeypatch.setattr(email_notifier.config, "EMAIL_RECEIVER", "r@example.com")
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)

    email_notifier.send_email_alert("subj", "body")

    assert _FakeSMTP.last_kwargs is not None
    assert _FakeSMTP.last_kwargs.get("timeout") == email_notifier.SMTP_TIMEOUT_SECONDS


def test_send_swallows_smtp_errors(monkeypatch, capsys):
    def _boom(*a, **k):
        raise TimeoutError("simulated stall")

    monkeypatch.setattr(email_notifier.config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(email_notifier.config, "EMAIL_SENDER", "s@example.com")
    monkeypatch.setattr(email_notifier.config, "EMAIL_PASSWORD", "pw")
    monkeypatch.setattr(email_notifier.config, "EMAIL_RECEIVER", "r@example.com")
    monkeypatch.setattr(smtplib, "SMTP_SSL", _boom)

    # Must not raise.
    email_notifier.send_email_alert("subj", "body")
    assert "Failed to send email notification" in capsys.readouterr().out
```

Note on imports: the suite runs with `pythonpath = src` (`pytest.ini`) and
tests import via the package name, e.g. `from bigdataball import email_notifier`
— confirm by checking an existing test's import line (e.g.
`tests/test_dk_matching.py`) and match whatever it uses.

**Verify**: `python -m pytest -q tests/test_email_notifier.py` → `2 passed`

### Step 3: Confirm the full suite still passes

**Verify**: `python -m pytest -q` → `70 passed` (68 existing + 2 new).

If the count is 69 (only one new test collected) or anything else unexpected,
re-check Step 2. Do not proceed to updating the index until the full suite is
green.

### Step 4: Update the plans index

In `plans/README.md`, add a status row for plan 015 in the "Execution order &
status" table and mark it DONE with the date and verified test count. Follow the
exact formatting of the existing rows.

## Test plan

- New file `tests/test_email_notifier.py`, 2 tests:
  - `test_send_passes_timeout` — the `timeout` kwarg reaches `SMTP_SSL` and
    equals `SMTP_TIMEOUT_SECONDS` (the regression this plan fixes).
  - `test_send_swallows_smtp_errors` — a raising `SMTP_SSL` (simulating a
    timeout) is caught, prints the existing "Failed to send" line, and does not
    propagate.
- Structural pattern: plain monkeypatch-based unit test like
  `tests/test_dk_matching.py` (no DB, no env seam needed here).
- Verification: `python -m pytest -q` → all pass, including the 2 new tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "timeout=SMTP_TIMEOUT_SECONDS" src/bigdataball/email_notifier.py` returns the `SMTP_SSL(...)` line
- [ ] `grep -n "SMTP_TIMEOUT_SECONDS = 30" src/bigdataball/email_notifier.py` returns the constant definition
- [ ] `python -m pytest -q tests/test_email_notifier.py` → `2 passed`
- [ ] `python -m pytest -q` → `70 passed`
- [ ] `git status --short` shows only `src/bigdataball/email_notifier.py`, `tests/test_email_notifier.py`, and `plans/README.md` modified/created
- [ ] `plans/README.md` status row for 015 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `email_notifier.py` does not match the "Current state" excerpt (it changed
  since this plan was written — e.g. a timeout or `logging` was already added).
- The full suite is not green at `68 passed` *before* your changes (drift check
  fails — the baseline this plan assumes no longer holds).
- Adding the timeout keyword raises a `TypeError` on the target Python version
  (it should not — `timeout` is a documented `SMTP_SSL` parameter; if it does,
  the environment is unusual and you should report it rather than work around
  it).

## Maintenance notes

- The 30-second value is a conservative default; a reviewer may want it lower.
  It is intentionally a named constant so it's trivial to tune.
- If a future change migrates the pipeline off Windows Task Scheduler to a
  scheduled runner with its own step timeout (a deferred direction item in
  `plans/README.md`), this per-send timeout still matters — a runner-level
  timeout would kill the whole job, losing the "COMPLETED WITH ERRORS" email
  this timeout preserves.
- Reviewer should confirm the timeout is on the `SMTP_SSL` constructor (which
  covers connect + all subsequent ops) and not only wrapped around `.connect()`.
