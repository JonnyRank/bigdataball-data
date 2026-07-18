import os


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BIGDATABALL_DATA_DIR", "/tmp/bdb_override")
    import paths
    assert paths.resolve_base_data_path() == "/tmp/bdb_override"


def test_fallback_to_local_data(monkeypatch):
    monkeypatch.delenv("BIGDATABALL_DATA_DIR", raising=False)
    import paths
    # Simulate a machine without the Google Drive mount so the local Data/
    # fallback is reachable even on dev machines where G:\My Drive exists.
    real_exists = os.path.exists
    monkeypatch.setattr(
        paths.os.path,
        "exists",
        lambda p: False if p == r"G:\My Drive" else real_exists(p),
    )
    result = paths.resolve_base_data_path()
    expected = os.path.join(os.path.dirname(os.path.abspath(paths.__file__)), "Data")
    assert result == expected
