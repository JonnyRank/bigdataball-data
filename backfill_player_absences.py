# backfill_player_absences.py
# One-shot CLI to backfill historical DNP-DND-NWT absence data into
# player_absences from already-archived BigDataBall player-feed files.
#
# Unlike daily_player_upload.py, this script reads archived files IN PLACE
# and never moves or renames them -- it is meant to be run once per past
# season against the season's already-archived feed file(s). Ingestion
# logic is shared with the daily pipeline via absence_ingestion.py.
#
# Usage:
#   python backfill_player_absences.py "path/to/2023-24 season file.xlsx" ["path/to/2024-25 file.xlsx" ...]
import argparse
import os
import sys

from sqlalchemy import create_engine

import absence_ingestion
import paths

EPILOG = """\
Note: BigDataBall player-feed files are cumulative for the whole season, so
the correct input for each past season is the LATEST archived file of that
season only -- do not pass every archived file for a season, just the most
recent one (earlier files are strict subsets of it).
"""


def main():
    parser = argparse.ArgumentParser(
        description="Backfill player_absences from archived BigDataBall player-feed .xlsx files.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Path(s) to one or more archived .xlsx player-feed files.",
    )
    args = parser.parse_args()

    base_data_path = paths.resolve_base_data_path()
    db_path = os.path.join(base_data_path, "nba_fantasy_logs.db")
    engine = create_engine(f"sqlite:///{db_path}")

    # Initialize ONCE before the loop, same "accumulate across files in one
    # run" pattern used by the daily pipeline.
    existing_keys = absence_ingestion.load_existing_absence_keys(engine)

    for file_path in args.files:
        inserted, sheet_found = absence_ingestion.ingest_absences(
            file_path, engine, existing_keys
        )
        if not sheet_found:
            print(
                f"ERROR: no '{absence_ingestion.ABSENCE_SHEET_NAME}' sheet in {file_path} "
                "-- this season may predate the sheet."
            )
            sys.exit(1)
        print(f"{file_path}: inserted {inserted} rows")


if __name__ == "__main__":
    main()
