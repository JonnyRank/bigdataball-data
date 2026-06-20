import importlib


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", "/tmp/bdb_override")
    import paths
    importlib.reload(paths)
    assert paths.resolve_base_data_path() == "/tmp/bdb_override"


def test_fallback_to_local_data(monkeypatch):
    monkeypatch.delenv("BIGDATABALL_DATA_DIR", raising=False)
    import paths
    importlib.reload(paths)
    result = paths.resolve_base_data_path()
    # On a machine without the G: mount, this is <repo>/Data.
    assert result.endswith("Data")
