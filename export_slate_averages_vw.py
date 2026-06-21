# export_slate_averages.py
# Objectives:
# 1. Locate and read 'DKEntries.csv' from the user's Downloads folder
# 2. Extract player names and fuzzy match them to the database
# 3. Dynamically CREATE A SQL VIEW (vw_daily_slate) restricted to these players
# 4. This View can then be queried by Excel or other tools directly

import pandas as pd
from sqlalchemy import create_engine, text
import os
import dk_matching
import paths

# from datetime import datetime


def run_slate_averages_pipeline():
    print("--- Starting Slate Averages Pipeline (View Creation) ---")

    # --- 1. Setup Paths ---
    BASE_DATA_PATH = paths.resolve_base_data_path()

    DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")

    # --- 2. Load DK Entries ---
    DK_FILE_PATH = dk_matching.find_dk_file_path()
    dk_names = dk_matching.load_dk_names(DK_FILE_PATH)
    if dk_names is None:
        return []
    print(f"DK File contains {len(dk_names)} unique players.")

    unmatched_names = []
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

        print(f"Identified {len(final_names_to_query)} valid database players.")

        # --- 5. Create the View ---
        sql_names_string = dk_matching.to_sql_in_list(final_names_to_query)

        view_name = "vw_daily_slate"

        drop_view_sql = f"DROP VIEW IF EXISTS {view_name}"

        # NOTE: We included the explicit CASTs from the previous step here too
        create_view_sql = f"""
        CREATE VIEW {view_name} AS
        SELECT 
            SEASON, 
            PLAYER, 
            TEAM, 
            CAST(GP AS INTEGER) AS GP,
            CAST(GS AS INTEGER) AS GS,
            MPG, 
            GSMPG, 
            FPPG, 
            GSFPPG, 
            FPPM, 
            GSFPPM, 
            STDV_FPPG as STDV
        FROM 
            vw_player_averages_regular_season
        WHERE 
            SEASON in ('2024-25', '2025-26')
            AND PLAYER IN ('{sql_names_string}')
        ORDER BY
            TEAM, PLAYER, SEASON desc
        """

        # USE engine.begin() - Automatically commits the view to disk
        try:
            with engine.begin() as connection:
                connection.execute(text(drop_view_sql))
                connection.execute(text(create_view_sql))

            print(
                f"SUCCESS: View '{view_name}' has been updated with {len(final_names_to_query)} players."
            )
            print("You can now query 'vw_daily_slate' directly from Excel.")

        except Exception as e:
            print(f"*** Error updating view: {e} ***")

        # --- 6. Create the L30 View ---
        view_name_l30 = "vw_daily_slate_l30"
        drop_view_l30_sql = f"DROP VIEW IF EXISTS {view_name_l30}"

        # This new view includes L30FPPM and is filtered to only the 2025-26 season.
        create_view_l30_sql = f"""
        CREATE VIEW {view_name_l30} AS
        SELECT
            SEASON,
            PLAYER,
            TEAM,
            CAST(GP AS INTEGER) AS GP,
            CAST(GS AS INTEGER) AS GS,
            MPG,
            GSMPG,
            FPPG,
            GSFPPG,
            FPPM,
            L30FPPM,
            GSFPPM,
            STDV_FPPG as STDV
        FROM
            vw_player_averages_regular_season
        WHERE
            SEASON = '2025-26'
            AND PLAYER IN ('{sql_names_string}')
        ORDER BY
            TEAM, PLAYER
        """
        try:
            with engine.begin() as connection:
                connection.execute(text(drop_view_l30_sql))
                connection.execute(text(create_view_l30_sql))
            print(
                f"SUCCESS: View '{view_name_l30}' has been updated with {len(final_names_to_query)} players."
            )
        except Exception as e:
            print(f"*** Error updating view '{view_name_l30}': {e} ***")

    except Exception as e:
        print(f"*** An error occurred: {e} ***")

    return unmatched_names


if __name__ == "__main__":
    run_slate_averages_pipeline()
