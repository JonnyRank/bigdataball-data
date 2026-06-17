import os

import pandas as pd

from tests.helpers import write_player_xlsx, make_rows


def _count(engine, table):
    return len(pd.read_sql_query(f"SELECT * FROM {table}", engine))


def test_single_file_loads_logs_and_learns_players(player_upload):
    mod = player_upload
    rows = make_rows([
        (1, "Alpha Player", "2025-11-01", 30),
        (2, "Beta Player", "2025-11-01", 20),
        (1, "Alpha Player", "2025-11-02", 25),
    ])
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed1.xlsx"), rows)

    processed, overwritten = mod.main()

    assert processed == 1
    assert _count(mod.engine, "player_logs") == 3      # all three game logs inserted
    assert _count(mod.engine, "dim_players") == 2      # two distinct players learned


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
    assert _count(mod.engine, "player_logs") == 2

    # Second run with an identical file (dedup is against rows already in the DB)
    write_player_xlsx(os.path.join(mod.NEW_FILES_FOLDER, "feed2.xlsx"), rows)
    mod.main()
    assert _count(mod.engine, "player_logs") == 2  # still 2 — no duplicates
