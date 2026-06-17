import importlib
import sys

import pytest


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
