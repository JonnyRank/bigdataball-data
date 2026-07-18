import importlib
import sys
import types

import pytest

_FANTASY_DEPS = [
    "daily_fantasy_log_upload",
    "daily_player_upload",
    "create_summary_tables",
    "export_slate_averages_vw",
    "export_playoffs_slate_averages_vw",
    "export_slate_averages_csv",
    "email_notifier",
    "drive_ingestion",
]

# Modules that require external services (Google APIs, SMTP) and must be stubbed
# so the fixture can import daily_fantasy_log_upload without network/credential deps.
_STUB_MODULES = {
    "drive_ingestion": {"main": lambda: None},
    "googleapiclient": {},
    "googleapiclient.discovery": {},
    "google": {},
    "google.oauth2": {},
    "google.oauth2.credentials": {},
    "google_auth_oauthlib": {},
    "google_auth_oauthlib.flow": {},
}


@pytest.fixture
def fantasy_upload(tmp_path, monkeypatch):
    """Imports daily_fantasy_log_upload fresh with BASE_DATA_PATH pointed at a temp dir.
    Returns the imported module; its engine, paths, and tables all live under tmp_path."""
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Fantasy_Logs").mkdir(parents=True)
    (data_dir / "Daily_Player_Logs").mkdir(parents=True)
    (data_dir / "Archived_Fantasy_Logs").mkdir(parents=True)
    (data_dir / "Archived_Player_Logs").mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

    for name in _FANTASY_DEPS:
        sys.modules.pop(name, None)

    # Stub modules that pull in external service dependencies
    stub_names_added = []
    for mod_name, attrs in _STUB_MODULES.items():
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            for attr, val in attrs.items():
                setattr(stub, attr, val)
            sys.modules[mod_name] = stub
            stub_names_added.append(mod_name)

    module = importlib.import_module("daily_fantasy_log_upload")

    # A test that drives main() to completion sends a REAL email when the
    # developer's .env has EMAIL_ENABLED — indistinguishable from a production
    # run. Wrap the sender so any such email is clearly marked as pytest
    # traffic. Tests that want to capture/suppress the email still monkeypatch
    # send_email_alert themselves, which replaces this wrapper.
    real_send = module.email_notifier.send_email_alert

    def send_marked_as_test(subject, body):
        real_send(
            f"[PYTEST] {subject}",
            "This email was sent by the pytest suite (fantasy_upload fixture), "
            "NOT by a production pipeline run.\n\n" + body,
        )

    monkeypatch.setattr(module.email_notifier, "send_email_alert", send_marked_as_test)

    yield module

    module.engine.dispose()
    for name in _FANTASY_DEPS:
        sys.modules.pop(name, None)
    for name in stub_names_added:
        sys.modules.pop(name, None)


@pytest.fixture
def player_upload(tmp_path, monkeypatch):
    """Imports daily_player_upload fresh with BASE_DATA_PATH pointed at a temp dir.
    Returns the imported module; its `engine`, paths, and tables all live under tmp_path."""
    data_dir = tmp_path / "data"
    (data_dir / "Daily_Player_Logs").mkdir(parents=True)
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", str(data_dir))

    # Force a fresh import so the module-level path/engine code re-runs with the env var.
    # (pop + import_module already yields a fresh import that reads the env var; do NOT
    # also call importlib.reload here — that would re-run module-level code a second time,
    # creating the engine twice and calling os.makedirs twice.)
    sys.modules.pop("daily_player_upload", None)
    module = importlib.import_module("daily_player_upload")

    yield module

    # Dispose the SQLAlchemy engine so its SQLite connection pool releases the
    # DB file before tmp_path cleanup (otherwise Windows can't delete the locked file).
    module.engine.dispose()
    sys.modules.pop("daily_player_upload", None)
