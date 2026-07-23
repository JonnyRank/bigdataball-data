import os

import pandas as pd
import pytest

from tests.helpers import write_fantasy_xlsx, make_fantasy_rows, count_rows


@pytest.fixture(autouse=True)
def _suppress_pipeline_email(fantasy_upload):
    """main() always sends a real notification email at the end of the run
    (config.EMAIL_ENABLED is hardcoded True). Suppress it for every test in
    this module so mod.main() doesn't perform real network I/O -- per the
    fantasy_upload fixture's own docstring guidance that tests wanting to
    suppress the email should monkeypatch send_email_alert themselves."""
    fantasy_upload.email_notifier.send_email_alert = lambda *a, **kw: None


def test_dedup_across_files_in_one_run(fantasy_upload):
    """Two cumulative fantasy log files in one run must not produce duplicate rows.
    Regression test for the existing_log_keys reset bug (symmetric with player upload)."""
    mod = fantasy_upload
    file1_rows = make_fantasy_rows([
        (1, "Alpha Player", "2025-11-01"),
        (1, "Alpha Player", "2025-11-02"),
    ])
    # file2 is cumulative: repeats file1's rows and adds one new game.
    file2_rows = make_fantasy_rows([
        (1, "Alpha Player", "2025-11-01"),
        (1, "Alpha Player", "2025-11-02"),
        (1, "Alpha Player", "2025-11-03"),
    ])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_01.xlsx"), file1_rows)
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_02.xlsx"), file2_rows)

    mod.main()  # processes both files in one run (sorted: feed_01 then feed_02)

    # Exactly 3 distinct game logs — feed_01's 2 rows must NOT be re-inserted from feed_02.
    assert count_rows(mod.engine, "fantasy_logs") == 3


def test_unique_index_exists_on_fantasy_logs(fantasy_upload):
    """ensure_unique_index must create a unique index on fantasy_logs after first ingest."""
    from sqlalchemy import inspect
    mod = fantasy_upload
    rows = make_fantasy_rows([(1, "Alpha Player", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()

    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("fantasy_logs")
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]


def test_single_file_loads_logs_and_learns_players(fantasy_upload):
    mod = fantasy_upload
    rows = make_fantasy_rows([
        (1, "Alpha Player", "2025-11-01"),
        (2, "Beta Player", "2025-11-01"),
        (1, "Alpha Player", "2025-11-02"),
    ])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    assert count_rows(mod.engine, "fantasy_logs") == 3
    assert count_rows(mod.engine, "dim_players") == 2


def test_player_name_standardization_applied(fantasy_upload):
    mod = fantasy_upload
    rows = make_fantasy_rows([(10, "GG Jackson", "2025-11-01")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    names = pd.read_sql_query("SELECT PLAYER FROM fantasy_logs", mod.engine)["PLAYER"].tolist()
    assert names == ["Gregory Jackson"]


def test_unwanted_columns_are_dropped(fantasy_upload):
    mod = fantasy_upload
    extra_cols = ["PLAYER_ID", "PLAYER", "DATE", "FANDUEL", "DRAFTKINGS1"]
    rows = [{"PLAYER_ID": 1, "PLAYER": "Alpha", "DATE": "2025-11-01", "FANDUEL": 30.5, "DRAFTKINGS1": 45.2}]
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows, cols=extra_cols)

    mod.main()

    from sqlalchemy import inspect
    inspector = inspect(mod.engine)
    col_names = [col["name"] for col in inspector.get_columns("fantasy_logs")]
    assert "FANDUEL" not in col_names
    assert "DK_POINTS" in col_names
    # The rename must preserve the value, not just the column name.
    points = pd.read_sql_query("SELECT DK_POINTS FROM fantasy_logs", mod.engine)["DK_POINTS"].tolist()
    assert points == [45.2]


def test_date_stored_as_iso_format(fantasy_upload):
    mod = fantasy_upload
    # Unambiguous non-ISO input proves format-agnostic normalization regardless
    # of pandas' month-first parser default.
    rows = make_fantasy_rows([(1, "Alpha", "November 1, 2025")])
    write_fantasy_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    dates = pd.read_sql_query("SELECT DATE FROM fantasy_logs", mod.engine)["DATE"].tolist()
    assert dates == ["2025-11-01"]
