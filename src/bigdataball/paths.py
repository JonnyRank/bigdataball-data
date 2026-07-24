import os


def resolve_base_data_path():
    """Resolve the base data directory used by the pipeline.

    Precedence:
      1. BIGDATABALL_DATA_DIR environment variable (tests and custom local runs).
      2. The Google Drive mount on the developer's machine.
      3. A local Data/ folder under the repository root (fallback).
    """
    override = os.environ.get("BIGDATABALL_DATA_DIR")
    if override:
        return override
    if os.path.exists(r"G:\My Drive"):
        return r"G:\My Drive\Documents\bigdataball"
    # Repo root: this module now lives at <repo>/src/bigdataball/paths.py,
    # so go up three levels to reach <repo> (keeps the local Data/ fallback correct).
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, "Data")
