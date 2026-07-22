import os

import pandas as pd

from tests.helpers import write_player_xlsx, make_rows, count_rows


def test_single_file_loads_logs_and_learns_players(player_upload):
    mod = player_upload
    rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (2, "Beta Player", "2025-11-01", 20),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    processed, overwritten, absences = mod.main()

    assert processed == 1
    assert count_rows(mod.engine, "player_logs") == 3      # all three game logs inserted
    assert count_rows(mod.engine, "dim_players") == 2      # two distinct players learned


def test_player_name_standardization_applied(player_upload):
    mod = player_upload
    # "GG Jackson" is mapped to "Gregory Jackson" in mappings.PLAYER_NAME_MAP
    rows = make_rows([(10, "GG Jackson", "2025-11-01", 18)])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    mod.main()

    names = pd.read_sql_query("SELECT PLAYER FROM player_logs", mod.engine)["PLAYER"].tolist()
    assert names == ["Gregory Jackson"]


def test_rerun_with_same_logs_inserts_no_duplicates(player_upload):
    mod = player_upload
    rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    # First run
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()
    assert count_rows(mod.engine, "player_logs") == 2

    # Second run with an identical file (dedup is against rows already in the DB)
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()
    assert count_rows(mod.engine, "player_logs") == 2  # still 2 — no duplicates


def test_dedup_across_files_in_one_run(player_upload):
    """Two cumulative files in the input folder must not produce duplicate logs.
    Regression test for the existing_log_keys reset bug."""
    mod = player_upload
    file1_rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    # file2 is a cumulative file: it repeats file1's logs and adds one new game.
    file2_rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (1, "Alpha Player", "2025-11-02", 25),
        (1, "Alpha Player", "2025-11-03", 28),
    ])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_01.xlsx"), file1_rows)
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed_02.xlsx"), file2_rows)

    mod.main()  # processes both files in one run (sorted: feed_01 then feed_02)

    # Exactly 3 distinct game logs — the two from file1 must NOT be re-inserted from file2.
    assert count_rows(mod.engine, "player_logs") == 3


def test_unique_index_prevents_silent_duplicate(player_upload):
    """After the first ingestion run, a second run with the same file must not insert
    duplicate rows — verified by checking the DB row count stays at 1, and the unique
    index created by ensure_unique_index must exist on player_logs."""
    from sqlalchemy import inspect
    mod = player_upload
    rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()

    # Write the same data again and re-run.
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()

    # Only one row — the in-memory dedup prevents the duplicate.
    assert count_rows(mod.engine, "player_logs") == 1

    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("player_logs")
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]


def test_unique_index_raises_on_duplicate_insert(player_upload):
    """The core plan-012 guarantee: a duplicate that slips past the in-memory
    dedup must fail loudly with IntegrityError instead of silently inflating
    averages. Insert a genuine duplicate directly (bypassing mod.main's
    in-memory key set) and assert the DB-level UNIQUE index rejects it."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    mod = player_upload
    rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)
    mod.main()  # creates table + unique index, inserts 1 row

    # Re-append the existing row straight to the DB, skipping the in-memory dedup.
    dup = pd.read_sql_query("SELECT * FROM player_logs", mod.engine)
    with pytest.raises(IntegrityError):
        dup.to_sql("player_logs", con=mod.engine, if_exists="append", index=False)

    # The rejected insert must not have added rows.
    assert count_rows(mod.engine, "player_logs") == 1
