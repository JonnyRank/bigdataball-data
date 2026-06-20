import os


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", "/tmp/bdb_override")
    import paths
    assert paths.resolve_base_data_path() == "/tmp/bdb_override"


def test_fallback_to_local_data(monkeypatch):
    monkeypatch.delenv("BIGDATABALL_DATA_DIR", raising=False)
    import paths
    result = paths.resolve_base_data_path()
    expected = os.path.join(os.path.dirname(os.path.abspath(paths.__file__)), "Data")
    assert result == expected
