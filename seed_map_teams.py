"""seed_map_teams.py — Create and populate the map_teams table.

Run this script once on a fresh DB (before running create_summary_tables.py) and
re-run it after the first real data ingestion so RAW_TEAM_NAME values are derived
from the actual fantasy_logs.TEAM strings rather than canonical guesses.

Usage:
    python seed_map_teams.py

If map_teams already has rows the script refuses to overwrite it to protect
hand-curated mappings.  Set BIGDATABALL_SEED_FORCE=1 to replace it:
    BIGDATABALL_SEED_FORCE=1 python seed_map_teams.py
"""

import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Abbreviation lookup
# ---------------------------------------------------------------------------
# Keys are matched case-insensitively (after whitespace normalisation) against
# raw TEAM strings coming from BigDataBall source files.
#
# NOTE: confirm the abbreviation convention (GS vs GSW, NY vs NYK, NO vs NOP,
# SA vs SAS, PHX vs PHO) against the real data before treating these as final.
# The dict covers several plausible raw-name formats; the actual keys that match
# depend on how BigDataBall formats team names in the source .xlsx files.
TEAM_ABBREVIATIONS = {
    "atlanta": "ATL", "atlanta hawks": "ATL",
    "boston": "BOS", "boston celtics": "BOS",
    "brooklyn": "BKN", "brooklyn nets": "BKN",
    "charlotte": "CHA", "charlotte hornets": "CHA",
    "chicago": "CHI", "chicago bulls": "CHI",
    "cleveland": "CLE", "cleveland cavaliers": "CLE",
    "dallas": "DAL", "dallas mavericks": "DAL",
    "denver": "DEN", "denver nuggets": "DEN",
    "detroit": "DET", "detroit pistons": "DET",
    "golden state": "GS", "golden state warriors": "GS",
    "houston": "HOU", "houston rockets": "HOU",
    "indiana": "IND", "indiana pacers": "IND",
    "la clippers": "LAC", "los angeles clippers": "LAC", "clippers": "LAC",
    "la lakers": "LAL", "los angeles lakers": "LAL", "lakers": "LAL",
    "memphis": "MEM", "memphis grizzlies": "MEM",
    "miami": "MIA", "miami heat": "MIA",
    "milwaukee": "MIL", "milwaukee bucks": "MIL",
    "minnesota": "MIN", "minnesota timberwolves": "MIN",
    "new orleans": "NO", "new orleans pelicans": "NO",
    "new york": "NY", "new york knicks": "NY",
    "oklahoma city": "OKC", "oklahoma city thunder": "OKC",
    "orlando": "ORL", "orlando magic": "ORL",
    "philadelphia": "PHI", "philadelphia 76ers": "PHI",
    "phoenix": "PHX", "phoenix suns": "PHX",
    "portland": "POR", "portland trail blazers": "POR",
    "sacramento": "SAC", "sacramento kings": "SAC",
    "san antonio": "SA", "san antonio spurs": "SA",
    "toronto": "TOR", "toronto raptors": "TOR",
    "utah": "UTA", "utah jazz": "UTA",
    "washington": "WAS", "washington wizards": "WAS",
}


def normalize(name):
    """Lower-case and collapse internal whitespace."""
    return " ".join(str(name).split()).lower()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _map_teams_row_count(conn):
    try:
        return conn.execute("SELECT COUNT(*) FROM map_teams").fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # table doesn't exist yet


def write_map_teams(conn, rows, force=None):
    """Write rows to map_teams, creating (or replacing) the table.

    rows: list of (raw_team_name, team_abbreviation_or_None).

    Refuses to overwrite a populated map_teams unless `force` is truthy
    (defaults to the BIGDATABALL_SEED_FORCE env var).  Raises RuntimeError
    otherwise.
    """
    if force is None:
        force = bool(os.environ.get("BIGDATABALL_SEED_FORCE"))
    if _map_teams_row_count(conn) > 0 and not force:
        raise RuntimeError(
            "map_teams already has rows; refusing to overwrite. "
            "Re-run with BIGDATABALL_SEED_FORCE=1 to replace it."
        )
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS map_teams")
    cur.execute(
        "CREATE TABLE map_teams (RAW_TEAM_NAME TEXT, TEAM_ABBREVIATION TEXT)"
    )
    cur.executemany(
        "INSERT INTO map_teams (RAW_TEAM_NAME, TEAM_ABBREVIATION) VALUES (?, ?)",
        rows,
    )
    conn.commit()


def _distinct_team_names(conn):
    """Distinct raw TEAM values from fantasy_logs (then player_logs).

    Returns [] if neither table exists or neither has a TEAM column.
    Prefers fantasy_logs; falls through to player_logs only if fantasy_logs
    yields no results.
    """
    names = []
    for table in ("fantasy_logs", "player_logs"):
        try:
            rows = conn.execute(f"SELECT DISTINCT TEAM FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue  # table or column not present yet
        names.extend(r[0] for r in rows if r[0] is not None)
        if names:
            break  # prefer fantasy_logs; fall through to player_logs only if empty
    # de-duplicate while preserving order
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _canonical_rows():
    """Best-effort 30-row seed for a completely empty DB.

    Uses the multi-word keys in TEAM_ABBREVIATIONS (the full 'City Nickname'
    forms), title-cased back to a plausible raw team name.  These are GUESSES
    and should be replaced by re-running seed_map_teams.py after the first real
    data ingestion.
    """
    rows = []
    for key, abbr in TEAM_ABBREVIATIONS.items():
        if " " in key and key not in ("la clippers", "la lakers"):
            rows.append((key.title(), abbr))
    # Deduplicate by abbreviation, keeping the first occurrence.
    seen = set()
    unique = []
    for raw, abbr in rows:
        if abbr not in seen:
            seen.add(abbr)
            unique.append((raw, abbr))
    return unique


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        import paths
        base = paths.resolve_base_data_path()
    except Exception:
        # Replicate the three-way path resolution used by other scripts in this repo:
        # BIGDATABALL_DATA_DIR env var (used by tests and local overrides) →
        # G:\My Drive mount → local Data/ folder.
        if os.environ.get("BIGDATABALL_DATA_DIR"):
            base = os.environ["BIGDATABALL_DATA_DIR"]
        elif os.path.exists(r"G:\My Drive"):
            base = r"G:\My Drive\Documents\bigdataball"
        else:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")
    db_path = os.path.join(base, "nba_fantasy_logs.db")

    conn = sqlite3.connect(db_path)
    try:
        raw_names = _distinct_team_names(conn)

        if raw_names:
            rows = [(name, TEAM_ABBREVIATIONS.get(normalize(name))) for name in raw_names]
        else:
            print(
                "WARNING: no fantasy_logs/player_logs found; seeding canonical guesses. "
                "Re-run seed_map_teams.py after the first data ingestion so RAW_TEAM_NAME "
                "values match the actual data."
            )
            rows = _canonical_rows()

        try:
            write_map_teams(conn, rows)
        except RuntimeError as exc:
            sys.exit(f"ERROR: {exc}")

        unmatched = [r for r, abbr in rows if abbr is None]
        print(
            f"Wrote {len(rows)} rows to map_teams "
            f"({len(rows) - len(unmatched)} matched, {len(unmatched)} unmatched)."
        )
        if unmatched:
            print(
                "ERROR: the following raw team names have no abbreviation mapping. "
                "Their players will be silently excluded from fantasy_averages by the "
                "TEAM_ABBREVIATION groupby in create_summary_tables.py. "
                "Add them to TEAM_ABBREVIATIONS in seed_map_teams.py and re-run:"
            )
            for r in unmatched:
                print(f"  - {r!r}")
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
