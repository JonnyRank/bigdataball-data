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
from thefuzz import process 

def run_slate_averages_smart_export():
    print("--- Starting Smart Slate Averages Export ---")

    # --- 1. Setup Paths ---
    if os.path.exists(r"G:\My Drive"):
        BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
    else:
        PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
    
    DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
    CSV_EXPORT_DIR = os.path.join(BASE_DATA_PATH, "csv_exports")
    DOWNLOADS_FOLDER = os.path.join(os.path.expanduser('~'), 'Downloads')
    DK_FILE_PATH = os.path.join(DOWNLOADS_FOLDER, "DKEntries.csv")

    # --- 2. Load DK Entries ---
    if not os.path.exists(DK_FILE_PATH):
        print(f"ERROR: Could not find file at {DK_FILE_PATH}")
        return

    # Find the header row by looking for the specific "Position,Name + ID" signature
    # This handles files where the header is indented or buried in instruction text
    print(f"Reading file: {DK_FILE_PATH}")
    header_row_index = 0
    with open(DK_FILE_PATH, 'r') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines[:50]): # Check first 50 lines
        # We look for the unique column sequence found in DK player lists
        if "Position" in line and "Name + ID" in line:
            header_row_index = i
            print(f"Found header at row {i}")
            break
            
    try:
        # Load CSV using the detected header row
        dk_df = pd.read_csv(DK_FILE_PATH, header=header_row_index)
        
        # Verify 'Name' column exists
        if 'Name' not in dk_df.columns:
            print("ERROR: Could not find 'Name' column. Please check CSV format.")
            print(f"Columns found: {dk_df.columns.tolist()}")
            return

        dk_df = dk_df.dropna(subset=['Name'])
        dk_names = dk_df['Name'].unique().tolist()
        
        print(f"DK File contains {len(dk_names)} unique players.")

        # --- 3. Fetch VALID names from Database ---
        engine = create_engine(f"sqlite:///{DB_PATH}")
        
        print("Fetching valid player list from database...")
        db_players_query = "SELECT DISTINCT PLAYER FROM vw_player_averages_regular_season"
        db_players_df = pd.read_sql_query(db_players_query, engine)
        valid_db_names = db_players_df['PLAYER'].tolist()

        # --- 4. Fuzzy Match Logic ---
        print("Matching names...")
        final_names_to_query = []
        
        for dk_name in dk_names:
            # Extract the best match from the DB list
            match, score = process.extractOne(dk_name, valid_db_names)
            
            # Threshold: 90 is usually safe for "AJ" vs "A.J." or "Smith" vs "Smith Jr."
            if score >= 90:
                final_names_to_query.append(match)
                if dk_name != match:
                    print(f"   > Mapped '{dk_name}' -> '{match}' (Score: {score})")
            else:
                # Optional: print skipped names to debug missing players
                # print(f"   x Skipped '{dk_name}' (Best: {match}, Score: {score})")
                pass

        final_names_to_query = list(set(final_names_to_query))
        print(f"Identified {len(final_names_to_query)} valid database players to query.")

        # --- 5. Construct & Run Final Query ---
        # Escape single quotes for SQL safety
        formatted_names = [name.replace("'", "''") for name in final_names_to_query]
        sql_names_string = "', '".join(formatted_names)
        
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