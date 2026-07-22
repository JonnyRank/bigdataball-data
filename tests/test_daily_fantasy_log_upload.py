import os

from tests.helpers import write_fantasy_xlsx, make_fantasy_rows, count_rows


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
