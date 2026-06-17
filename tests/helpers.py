import pandas as pd


def write_player_xlsx(path, rows):
    """rows: list of dicts with keys PLAYER_ID, PLAYER, DATE (and optional stats).
    Writes an .xlsx with header on row 0, matching daily_player_upload's read_excel."""
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER", "DATE", "PTS"])
    df.to_excel(path, index=False)


def write_fantasy_xlsx(path, rows):
    """Write a fantasy log .xlsx matching daily_fantasy_log_upload's read format.

    daily_fantasy_log_upload reads with header=1 (column names on xlsx row 1) then
    skips the first DataFrame row via iloc[1:].  So this helper writes:
      xlsx row 0: empty  (before the header — ignored by pandas)
      xlsx row 1: column names  (header=1 target)
      xlsx row 2: dummy row     (consumed by iloc[1:] and discarded)
      xlsx row 3+: actual data
    """
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
