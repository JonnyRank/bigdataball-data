# absence_ingestion.py
# Reads the DNP-DND-NWT sheet from a BigDataBall player-feed .xlsx and
# appends new rows to player_absences, learning unknown players into
# dim_players. Shared by daily_player_upload.py and backfill_player_absences.py.
#
# This module intentionally does NOT resolve paths or create its own engine
# at module level -- callers (the daily pipeline, the backfill CLI, and
# tests) inject their own `engine` so it can be reused across contexts.
import pandas as pd
from sqlalchemy import text
import mappings

ABSENCES_TABLE_NAME = "player_absences"
PLAYERS_TABLE_NAME = "dim_players"
ABSENCE_SHEET_NAME = "DNP-DND-NWT"
DNP_CD_REASON = "COACH'S DECISION"

# The sanitizer (see _sanitize_columns) turns the raw feed headers
# (GAME DATE, GAME-ID, TEAM, OPPONENT, PLAYER-ID, PLAYER NAME, STATUS,
# REASON) into GAME_DATE / PLAYER_NAME / etc. Those two differ from the
# repo-wide log-table convention (player_logs / fantasy_logs use DATE and
# PLAYER), so they are renamed to match -- every table keyed per player per
# game shares the same column names.
RENAME_MAP = {
    "GAME_DATE": "DATE",
    "PLAYER_NAME": "PLAYER",
}

# Column names expected after sanitization + renaming.
EXPECTED_COLUMNS = [
    "DATE",
    "GAME_ID",
    "TEAM",
    "OPPONENT",
    "PLAYER_ID",
    "PLAYER",
    "STATUS",
    "REASON",
]


def _sanitize_columns(columns):
    """Same header sanitization as daily_player_upload.py: newlines/hyphens/
    spaces -> underscore, strip anything non-alphanumeric/underscore, upper."""
    return (
        columns.str.replace("\n", "_")
        .str.replace("-", "_")
        .str.replace(" ", "_")
        .str.replace(r"[^a-zA-Z0-9_]", "", regex=True)
        .str.upper()
    )


def ensure_unique_index(engine):
    """Unique index on (PLAYER_ID, DATE) — DB-level backstop for the in-memory
    absence_key dedup. Safe to call before the table exists (guards `no such table`)
    so an already-populated player_absences gets indexed even on a run that inserts
    zero new rows; also called right after to_sql so a first-ever insert is covered."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{ABSENCES_TABLE_NAME}_player_date
                ON {ABSENCES_TABLE_NAME} ("PLAYER_ID", "DATE")
                """
                )
            )
    except Exception as e:
        if "no such table" in str(e):
            pass  # table not created yet; the post-to_sql call will create the index
        else:
            raise


def load_existing_absence_keys(engine):
    """Returns set of 'PLAYER_ID_DATE' keys already in player_absences.
    Empty set if the table doesn't exist yet (first run)."""
    try:
        df = pd.read_sql(
            f'SELECT DISTINCT "PLAYER_ID", "DATE" FROM {ABSENCES_TABLE_NAME}',
            engine,
        )
        return set(df["PLAYER_ID"].astype(str) + "_" + df["DATE"].astype(str))
    except Exception as e:
        if "no such table" in str(e):
            return set()
        raise


def _load_box_score_keys(engine):
    """Returns set of 'PLAYER_ID_DATE' keys already present in player_logs
    (box scores), used to resolve the box-score-wins conflict policy.

    Tolerates a missing player_logs table (a standalone backfill_player_absences.py
    run can call this before any box scores exist) -- treated as an empty key set
    rather than raising.

    The absence side normalizes DATE to %Y-%m-%d (see ingest_absences), so the
    stored player_logs.DATE is re-normalized here too before building the key --
    otherwise a differently-formatted box-score DATE (e.g. "2025-11-01 00:00:00")
    would silently fail to match and let an absence row through for a date the
    player actually played. Mirrors daily_player_upload.py's own dedup, which
    likewise re-normalizes stored DATE before comparing.
    """
    try:
        df = pd.read_sql('SELECT "PLAYER_ID", "DATE" FROM player_logs', engine)
        dates = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")
        return set(df["PLAYER_ID"].astype(str) + "_" + dates)
    except Exception as e:
        if "no such table" in str(e):
            return set()
        raise


def ingest_absences(file_path, engine, existing_keys):
    """Process one file's DNP-DND-NWT sheet.

    Mutates existing_keys in place (adds keys it inserts) so the caller can
    process multiple cumulative files in one run without duplicates -- same
    pattern as the existing_log_keys fix for player_logs; the key set is
    initialized ONCE by the caller, never inside a per-file loop.

    Returns (inserted_count, sheet_found: bool).
    """
    # Indexes an already-populated player_absences even on a run that ends up
    # inserting zero new rows; no-ops (via the "no such table" guard) on a
    # brand-new DB where the table doesn't exist yet.
    ensure_unique_index(engine)

    try:
        df = pd.read_excel(file_path, sheet_name=ABSENCE_SHEET_NAME)
    except ValueError:
        # Sheet not present in this workbook (e.g. a season that predates it).
        return 0, False

    df = df.dropna(how="all").copy()

    # --- Sanitize headers (same snippet as daily_player_upload.py), then
    # rename to the repo-wide log-table convention (DATE, PLAYER) ---
    df.columns = _sanitize_columns(df.columns)
    df.rename(columns=RENAME_MAP, inplace=True)

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"'{ABSENCE_SHEET_NAME}' sheet in {file_path} is missing expected "
            f"column(s) {missing} after sanitization/renaming; found {list(df.columns)}."
        )

    # --- Normalizations ---
    df["DATE"] = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")
    df["GAME_ID"] = df["GAME_ID"].astype(int)
    df["PLAYER_ID"] = df["PLAYER_ID"].astype(int)

    changed_mask = df["PLAYER"].isin(mappings.PLAYER_NAME_MAP)
    if changed_mask.any():
        print(
            f"  > Standardizing absence player names: {df.loc[changed_mask, 'PLAYER'].unique().tolist()}"
        )
    df["PLAYER"] = df["PLAYER"].replace(mappings.PLAYER_NAME_MAP)

    # --- Derived column ---
    # Normalize case/whitespace before comparing so a feed variant like
    # "Coach's Decision " can't silently miscategorize as INJURY/ILLNESS/OTHER.
    df["ABSENCE_TYPE"] = df["REASON"].apply(
        lambda r: "DNP-CD"
        if str(r).strip().upper() == DNP_CD_REASON
        else "INJURY/ILLNESS/OTHER"
    )

    # --- Conflict filter: box score wins ---
    df["absence_key"] = df["PLAYER_ID"].astype(str) + "_" + df["DATE"].astype(str)
    box_score_keys = _load_box_score_keys(engine)
    conflict_mask = df["absence_key"].isin(box_score_keys)
    if conflict_mask.any():
        print(
            f"  > Skipped {int(conflict_mask.sum())} absence row(s) with a conflicting box-score record."
        )
        df = df.loc[~conflict_mask].copy()

    # --- Dedup against absence rows already inserted (this run or earlier) ---
    truly_new_df = df.loc[~df["absence_key"].isin(existing_keys)].copy()

    if truly_new_df.empty:
        return 0, True

    # --- Learn new players into dim_players (same pattern as daily_player_upload) ---
    new_players_df = truly_new_df[["PLAYER_ID", "PLAYER"]].drop_duplicates(
        subset=["PLAYER_ID"]
    )
    existing_players_df = pd.read_sql(
        f'SELECT "PLAYER_ID" FROM {PLAYERS_TABLE_NAME}', engine
    )
    existing_ids = set(existing_players_df["PLAYER_ID"])
    truly_new_players_df = new_players_df.loc[
        ~new_players_df["PLAYER_ID"].isin(existing_ids)
    ]
    if not truly_new_players_df.empty:
        print(
            f"  > Adding {len(truly_new_players_df)} new player(s) to {PLAYERS_TABLE_NAME} from absences..."
        )
        # dim_players uses PLAYER_NAME (same rename as daily_player_upload).
        truly_new_players_df.rename(columns={"PLAYER": "PLAYER_NAME"}).to_sql(
            PLAYERS_TABLE_NAME, con=engine, if_exists="append", index=False
        )

    # --- Append surviving rows to player_absences ---
    insert_df = truly_new_df.drop(columns=["absence_key"])[
        [
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
    ]
    insert_df.to_sql(ABSENCES_TABLE_NAME, con=engine, if_exists="append", index=False)
    ensure_unique_index(engine)  # idempotent; creates index on first run

    existing_keys.update(truly_new_df["absence_key"])

    return len(truly_new_df), True
