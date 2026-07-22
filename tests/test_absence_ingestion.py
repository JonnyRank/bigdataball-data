import os

import pandas as pd

from tests.helpers import (
    count_rows,
    make_absence_rows,
    make_rows,
    write_player_xlsx,
    write_player_xlsx_with_absences,
)


def _absence_row_count(engine):
    """Tolerant row count: player_absences may not exist yet (table is
    created implicitly by to_sql on first insert)."""
    try:
        return count_rows(engine, "player_absences")
    except Exception as e:
        if "no such table" in str(e):
            return 0
        raise


def test_single_file_loads_absences_and_learns_players(player_upload):
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    processed, overwritten, absences = mod.main()

    assert processed == 1
    assert absences == 1
    assert _absence_row_count(mod.engine) == 1

    dim_ids = pd.read_sql_query("SELECT PLAYER_ID FROM dim_players", mod.engine)[
        "PLAYER_ID"
    ].tolist()
    assert 99 in dim_ids  # absence-only player learned into dim_players

    absence_ids = pd.read_sql_query("SELECT PLAYER_ID FROM player_absences", mod.engine)[
        "PLAYER_ID"
    ].tolist()
    assert absence_ids == [99]


def test_absence_columns_match_log_table_convention(player_upload):
    """player_absences must use the repo-wide log-table column names
    (DATE, PLAYER) -- not the sheet's sanitized GAME_DATE / PLAYER_NAME --
    so cross-table queries and check_ingest_duplicates.py work unchanged."""
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    mod.main()

    columns = list(pd.read_sql_query("SELECT * FROM player_absences", mod.engine).columns)
    assert columns == [
        "DATE",
        "GAME_ID",
        "TEAM",
        "OPPONENT",
        "PLAYER_ID",
        "PLAYER",
        "STATUS",
        "REASON",
        "ABSENCE_TYPE",
    ]


def test_absence_type_derivation(player_upload):
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 91, "Player A", "DNP", "COACH'S DECISION"),
        ("2025-11-01", 22500001, "Houston", "Dallas", 92, "Player B", "DND", "REST"),
        ("2025-11-01", 22500001, "Houston", "Dallas", 93, "Player C", "DND", "INJURY/ILLNESS"),
        # Case/whitespace variant must still be recognized as a coach's decision.
        ("2025-11-01", 22500001, "Houston", "Dallas", 94, "Player D", "DNP", "Coach's Decision "),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    mod.main()

    rows = pd.read_sql_query(
        "SELECT PLAYER_ID, ABSENCE_TYPE FROM player_absences ORDER BY PLAYER_ID", mod.engine
    )
    lookup = dict(zip(rows["PLAYER_ID"], rows["ABSENCE_TYPE"]))
    assert lookup[91] == "DNP-CD"
    assert lookup[92] == "INJURY/ILLNESS/OTHER"
    assert lookup[93] == "INJURY/ILLNESS/OTHER"
    assert lookup[94] == "DNP-CD"


def test_rerun_with_same_file_inserts_no_duplicate_absences(player_upload):
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )
    mod.main()
    assert _absence_row_count(mod.engine) == 1

    # Rerun with a file of the same name/content — dedup must be against the DB.
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), player_rows, absence_rows
    )
    mod.main()
    assert _absence_row_count(mod.engine) == 1


def test_dedup_across_files_in_one_run(player_upload):
    """Two cumulative files processed in one run must not duplicate absence
    rows — same in-memory key-set pattern as the box-score dedup fix."""
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    file1_absences = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    # file2 is cumulative: repeats file1's absence row and adds one new one.
    file2_absences = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
        ("2025-11-02", 22500002, "Houston", "Dallas", 99, "Beta Bench", "DND", "REST"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed_01.xlsx"), player_rows, file1_absences
    )
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed_02.xlsx"), player_rows, file2_absences
    )

    mod.main()  # processes both files in one run (sorted: feed_01 then feed_02)

    assert _absence_row_count(mod.engine) == 2


def test_missing_absence_sheet_does_not_crash_daily_pipeline(player_upload):
    mod = player_upload
    rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    # Box-scores-only workbook (no DNP-DND-NWT sheet at all).
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    processed, overwritten, absences = mod.main()

    assert processed == 1  # file still processed and archived
    assert absences == 0
    assert _absence_row_count(mod.engine) == 0
    archived = os.path.join(mod.PROCESSED_FOLDER, "feed1.xlsx")
    assert os.path.exists(archived)


def test_conflict_rows_excluded_box_score_wins(player_upload):
    mod = player_upload
    # Player 50 has a real box-score line for game 22500001 — its absence
    # row for the same game is a known BigDataBall data-quality error and
    # must be dropped. Player 60 has no conflicting box score and must be
    # inserted normally, even though it's in the same file.
    player_rows = [
        {"GAME-ID": 22500001, "PLAYER_ID": 50, "PLAYER": "Conflict Player", "DATE": "2025-11-01", "PTS": 12},
    ]
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 50, "Conflict Player", "DNP", "COACH'S DECISION"),
        ("2025-11-01", 22500001, "Houston", "Dallas", 60, "Clean Player", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    mod.main()

    logs_ids = pd.read_sql_query("SELECT PLAYER_ID FROM player_logs", mod.engine)[
        "PLAYER_ID"
    ].tolist()
    assert logs_ids == [50]

    absence_ids = pd.read_sql_query("SELECT PLAYER_ID FROM player_absences", mod.engine)[
        "PLAYER_ID"
    ].tolist()
    assert absence_ids == [60]  # conflicting row (50) excluded; clean row (60) inserted


def test_absence_player_name_standardization(player_upload):
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 77, "GG Jackson", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    mod.main()

    absence_name = pd.read_sql_query(
        "SELECT PLAYER FROM player_absences WHERE PLAYER_ID = 77", mod.engine
    )["PLAYER"].tolist()
    assert absence_name == ["Gregory Jackson"]

    dim_name = pd.read_sql_query(
        "SELECT PLAYER_NAME FROM dim_players WHERE PLAYER_ID = 77", mod.engine
    )["PLAYER_NAME"].tolist()
    assert dim_name == ["Gregory Jackson"]


def test_game_id_normalization_matches_player_logs(player_upload):
    mod = player_upload
    # Box score for a different player in the same game, so no conflict —
    # this only exercises GAME_ID type/value agreement between the tables.
    player_rows = [
        {"GAME-ID": 22500001, "PLAYER_ID": 1, "PLAYER": "Alpha Player", "DATE": "2025-11-01", "PTS": 30},
    ]
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )

    mod.main()

    joined = pd.read_sql_query(
        """
        SELECT a.PLAYER_ID AS absence_player, p.PLAYER_ID AS log_player
        FROM player_absences a
        JOIN player_logs p ON a.GAME_ID = p.GAME_ID
        """,
        mod.engine,
    )
    assert len(joined) == 1
    assert joined.iloc[0]["absence_player"] == 99
    assert joined.iloc[0]["log_player"] == 1

    stored_game_id = pd.read_sql_query(
        "SELECT GAME_ID, typeof(GAME_ID) AS t FROM player_absences", mod.engine
    )
    assert stored_game_id.iloc[0]["GAME_ID"] == 22500001
    assert stored_game_id.iloc[0]["t"] == "integer"


def test_unique_index_exists_on_player_absences(player_upload):
    """ensure_unique_index must create a unique index on player_absences after
    the first absence insert."""
    from sqlalchemy import inspect
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    absence_rows = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DNP", "COACH'S DECISION"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), player_rows, absence_rows
    )
    mod.main()

    inspector = inspect(mod.engine)
    indexes = inspector.get_indexes("player_absences")
    matching = [idx for idx in indexes if "player_date" in idx["name"]]
    assert matching, f"Index not found. Indexes: {indexes}"
    assert matching[0]["unique"], f"Index exists but is not UNIQUE: {matching[0]}"
    assert matching[0]["column_names"] == ["PLAYER_ID", "DATE"], matching[0]


def test_absence_dedup_is_keyed_on_date_not_game_id(player_upload):
    """Across two files in one run, a second absence row sharing (PLAYER_ID, DATE)
    with the first but under a DIFFERENT GAME_ID must be deduped away — proving the
    in-memory key (and the index it must agree with) is DATE-based, not GAME_ID-based."""
    mod = player_upload
    player_rows = make_rows([(1, "Alpha Player", "2025-11-01", 30)])
    file1_absences = make_absence_rows([
        ("2025-11-01", 22500001, "Houston", "Dallas", 99, "Beta Bench", "DND", "REST"),
    ])
    file2_absences = make_absence_rows([
        ("2025-11-01", 22500002, "Houston", "Dallas", 99, "Beta Bench", "DND", "REST"),
    ])
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed_01.xlsx"), player_rows, file1_absences
    )
    write_player_xlsx_with_absences(
        os.path.join(mod.NEW_FILES_FOLDER, "feed_02.xlsx"), player_rows, file2_absences
    )
    mod.main()  # processes both files (sorted); must NOT raise — feed_02's row is deduped

    absence_dates = pd.read_sql_query(
        "SELECT PLAYER_ID, DATE FROM player_absences WHERE PLAYER_ID = 99", mod.engine
    )
    assert len(absence_dates) == 1, f"Expected 1 row (DATE-keyed dedup); got {len(absence_dates)}"
