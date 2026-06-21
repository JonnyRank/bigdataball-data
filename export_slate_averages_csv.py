# export_slate_averages_csv.py
# Objectives:
# 1. Locate and read 'DKEntries.csv' from the user's Downloads folder
# 2. Extract player names from the DraftKings file by robustly finding the correct header row
# 3. Connect to the SQLite database (nba_fantasy_logs.db)
# 4. Fetch the master list of valid player names from 'vw_player_averages_regular_season'
# 5. Use fuzzy matching (thefuzz) to map DraftKings names to Database names to handle spelling differences
# 6. Query the database for stats specific to the identified players
# 7. Export the results to a timestamped CSV in the 'csv_exports' folder

import pandas as pd
from sqlalchemy import create_engine
import os
from datetime import datetime
import dk_matching
import paths


def run_slate_averages_smart_export():
    print("--- Starting Smart Slate Averages Export ---")

    # --- 1. Setup Paths ---
    BASE_DATA_PATH = paths.resolve_base_data_path()

    DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
    CSV_EXPORT_DIR = os.path.join(BASE_DATA_PATH, "csv_exports")

    # --- 2. Load DK Entries ---
    DK_FILE_PATH = dk_matching.find_dk_file_path()
    dk_names = dk_matching.load_dk_names(DK_FILE_PATH)
    if dk_names is None:
        return

    print(f"DK File contains {len(dk_names)} unique players.")

    try:
        # --- 3. Fetch VALID names from Database ---
        engine = create_engine(f"sqlite:///{DB_PATH}")

        print("Fetching valid player list from database...")
        db_players_query = (
            "SELECT DISTINCT PLAYER FROM vw_player_averages_regular_season"
        )
        db_players_df = pd.read_sql_query(db_players_query, engine)
        valid_db_names = db_players_df["PLAYER"].tolist()

        # --- 4. Fuzzy Match Logic ---
        print("Matching names...")
        final_names_to_query, unmatched_names = dk_matching.match_names(
            dk_names, valid_db_names
        )

        if unmatched_names:
            print(
                f"\n--- WARNING: {len(unmatched_names)} players in DKEntries could not be matched to database ---"
            )
            for name in unmatched_names:
                print(f"   x {name}")
            print(
                "----------------------------------------------------------------------------------------------\n"
            )

        print(
            f"Identified {len(final_names_to_query)} valid database players to query."
        )

        # --- 5. Construct & Run Final Query ---
        sql_names_string = dk_matching.to_sql_in_list(final_names_to_query)

        query = f"""
        SELECT 
            SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
        FROM 
            vw_player_averages_regular_season
        WHERE 
            SEASON in ('2024-25', '2025-26')
            AND PLAYER IN ('{sql_names_string}')
        ORDER BY 
            TEAM, PLAYER, SEASON DESC;
        """

        results_df = pd.read_sql_query(query, engine)

        timestamp = datetime.now().strftime("%m-%d-%Y_%H%M%S")
        export_filename = f"slate_player_averages_{timestamp}.csv"
        export_path = os.path.join(CSV_EXPORT_DIR, export_filename)

        os.makedirs(CSV_EXPORT_DIR, exist_ok=True)
        results_df.to_csv(export_path, index=False)
        print(f"SUCCESS: Exported {len(results_df)} rows to: {export_path}")

        # --- 6. Create and Export the L30 CSV ---
        print("\n--- Creating L30 Slate Averages Export ---")
        query_l30 = f"""
        SELECT
            SEASON,
            PLAYER,
            TEAM,
            GP,
            GS,
            MPG,
            GSMPG,
            FPPG,
            GSFPPG,
            FPPM,
            GSFPPM,
            STDV_FPPG as STDV,
            L30FPPM
        FROM
            vw_player_averages_regular_season
        WHERE
            SEASON = '2025-26'
            AND PLAYER IN ('{sql_names_string}')
        ORDER BY
            TEAM, PLAYER
        """
        results_l30_df = pd.read_sql_query(query_l30, engine)
        export_l30_filename = f"slate_player_averages_l30_{timestamp}.csv"
        export_l30_path = os.path.join(CSV_EXPORT_DIR, export_l30_filename)
        results_l30_df.to_csv(export_l30_path, index=False)
        print(f"SUCCESS: Exported {len(results_l30_df)} rows to: {export_l30_path}")

    except Exception as e:
        print(f"*** An error occurred: {e} ***")


if __name__ == "__main__":
    run_slate_averages_smart_export()
