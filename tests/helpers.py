import pandas as pd


def write_player_xlsx(path, rows):
    """rows: list of dicts with keys PLAYER_ID, PLAYER, DATE (and optional stats).
    Writes an .xlsx with header on row 0, matching daily_player_upload's read_excel."""
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER", "DATE", "PTS"])
    df.to_excel(path, index=False)


def make_rows(specs):
    """specs: list of (player_id, player_name, date, pts) tuples."""
    return [
        {"PLAYER_ID": pid, "PLAYER": name, "DATE": date, "PTS": pts}
        for pid, name, date, pts in specs
    ]
