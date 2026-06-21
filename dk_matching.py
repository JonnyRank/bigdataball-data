import os

import mappings
from thefuzz import process

DK_FILENAME = "DKEntries.csv"
MATCH_THRESHOLD = 90


def find_dk_file_path():
    """Path to DKEntries.csv in the user's Downloads folder."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(downloads, DK_FILENAME)


def load_dk_names(dk_file_path):
    """Detect the header row and return the list of unique player names.

    Returns None if the file is missing, unreadable, or has no 'Name' column
    (callers treat None as 'abort this pipeline').
    """
    import pandas as pd  # deferred: callers of match_names/to_sql_in_list don't need it

    if not dk_file_path or not os.path.exists(dk_file_path):
        print(f"ERROR: Could not find file at {dk_file_path}")
        return None

    print(f"Reading file: {dk_file_path}")
    header_row_index = 0
    try:
        with open(dk_file_path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        for i, line in enumerate(lines[:50]):
            if "Position" in line and "Name + ID" in line:
                header_row_index = i
                break

        dk_df = pd.read_csv(dk_file_path, header=header_row_index, encoding="utf-8-sig")
        if "Name" not in dk_df.columns:
            print("ERROR: Could not find 'Name' column.")
            return None
        dk_df = dk_df.dropna(subset=["Name"])
        return dk_df["Name"].unique().tolist()
    except Exception as e:
        print(f"ERROR: Failed to read or parse DK file: {e}")
        return None


def match_names(dk_names, valid_db_names, threshold=MATCH_THRESHOLD):
    """Map DK names to DB names. Returns (matched_db_names, unmatched_descriptions).

    matched_db_names is de-duplicated (order not guaranteed), matching today's
    `list(set(...))`. Applies mappings.PLAYER_NAME_MAP before fuzzy matching.
    """
    matched = []
    unmatched = []
    # Strip None/NaN/non-string values that can appear when the DB view has NULL rows.
    valid_db_names = [n for n in valid_db_names if isinstance(n, str) and n.strip()]
    # Guard: process.extractOne raises on an empty choice list. If the DB/view returned
    # no players (a fresh DB, or an out-of-season playoffs view), treat every DK name as
    # unmatched rather than crashing the pipeline. This is a deliberate robustness
    # improvement over the original inline code (which would crash here).
    if not valid_db_names:
        unmatched = [
            f"{mappings.PLAYER_NAME_MAP.get(n, n)} (Best match: None, Score: 0)"
            for n in dk_names
        ]
        return [], unmatched
    for dk_name in dk_names:
        if dk_name in mappings.PLAYER_NAME_MAP:
            dk_name = mappings.PLAYER_NAME_MAP[dk_name]
        match, score = process.extractOne(dk_name, valid_db_names)
        if score >= threshold:
            matched.append(match)
        else:
            unmatched.append(f"{dk_name} (Best match: {match}, Score: {score})")
    return list(set(matched)), unmatched


def to_sql_in_list(names):
    """Single-quote-escape and join names for a SQL IN (...) clause."""
    if not names:
        return ""
    formatted = [name.replace("'", "''") for name in names]
    return "', '".join(formatted)
