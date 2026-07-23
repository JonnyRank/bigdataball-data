import pandas as pd


def count_rows(engine, table):
    return len(pd.read_sql_query(f"SELECT * FROM {table}", engine))


def write_player_xlsx(path, rows):
    """rows: list of dicts with keys PLAYER_ID, PLAYER, DATE (and optional stats).
    Writes an .xlsx with header on row 0, matching daily_player_upload's read_excel."""
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER", "DATE", "PTS"])
    df.to_excel(path, index=False)


def write_fantasy_xlsx(path, rows, cols=None):
    """Write a fantasy log .xlsx matching daily_fantasy_log_upload's read format.

    daily_fantasy_log_upload reads with header=1 (column names on xlsx row 1) then
    skips the first DataFrame row via iloc[1:].  So this helper writes:
      xlsx row 0: empty  (before the header — ignored by pandas)
      xlsx row 1: column names  (header=1 target)
      xlsx row 2: dummy row     (consumed by iloc[1:] and discarded)
      xlsx row 3+: actual data
    """
    if cols is None:
        cols = ["PLAYER_ID", "PLAYER", "DATE"]
    dummy = {c: None for c in cols}
    df = pd.DataFrame([dummy] + list(rows), columns=cols)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=1)


def make_rows(specs):
    """specs: list of (player_id, player_name, date, pts) tuples."""
    return [
        {"PLAYER_ID": pid, "PLAYER": name, "DATE": date, "PTS": pts}
        for pid, name, date, pts in specs
    ]


def make_fantasy_rows(specs):
    """specs: list of (player_id, player_name, date) tuples."""
    return [{"PLAYER_ID": pid, "PLAYER": name, "DATE": date} for pid, name, date in specs]


def write_player_xlsx_with_absences(path, player_rows, absence_rows):
    """Writes a two-sheet workbook shaped like the real BigDataBall player
    feed: a box-score sheet ("NBA-PLAYER") first, and the "DNP-DND-NWT"
    absence sheet second.

    player_rows: list of dicts with keys GAME-ID, PLAYER_ID, PLAYER, DATE,
    PTS. "GAME-ID" may be omitted (stored as a missing/None value) for rows
    that don't need to participate in the absence conflict filter.

    absence_rows: list of dicts using the raw feed headers -- GAME DATE,
    GAME-ID, TEAM, OPPONENT, PLAYER-ID, PLAYER NAME, STATUS, REASON. Use
    make_absence_rows() to build these from tuples.
    """
    box_cols = ["GAME-ID", "PLAYER_ID", "PLAYER", "DATE", "PTS"]
    box_df = pd.DataFrame(player_rows, columns=box_cols)

    absence_cols = [
        "GAME DATE",
        "GAME-ID",
        "TEAM",
        "OPPONENT",
        "PLAYER-ID",
        "PLAYER NAME",
        "STATUS",
        "REASON",
    ]
    absence_df = pd.DataFrame(absence_rows, columns=absence_cols)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        box_df.to_excel(writer, sheet_name="NBA-PLAYER", index=False)
        absence_df.to_excel(writer, sheet_name="DNP-DND-NWT", index=False)


def make_absence_rows(specs):
    """specs: list of (game_date, game_id, team, opponent, player_id,
    player_name, status, reason) tuples -> raw-feed-header dicts consumable
    by write_player_xlsx_with_absences."""
    return [
        {
            "GAME DATE": game_date,
            "GAME-ID": game_id,
            "TEAM": team,
            "OPPONENT": opponent,
            "PLAYER-ID": player_id,
            "PLAYER NAME": player_name,
            "STATUS": status,
            "REASON": reason,
        }
        for game_date, game_id, team, opponent, player_id, player_name, status, reason in specs
    ]
