# export_slate_averages.py
# Objectives:
# 1. Locate and read 'DKEntries.csv' from the user's Downloads folder
# 2. Extract player names and fuzzy match them to the database
# 3. Dynamically CREATE A SQL VIEW (vw_daily_slate) restricted to these players
# 4. This View can then be queried by Excel or other tools directly

import pandas as pd
from sqlalchemy import create_engine, text
import os
# from datetime import datetime
from thefuzz import process 

def run_slate_averages_pipeline():
    print("--- Starting Slate Averages Pipeline (View Creation) ---")

    # --- 1. Setup Paths ---
    if os.path.exists(r"G:\My Drive"):
        BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
    else:
        # Fallback to local
        PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")
    
    DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
    DOWNLOADS_FOLDER = os.path.join(os.path.expanduser('~'), 'Downloads')
    DK_FILE_PATH = os.path.join(DOWNLOADS_FOLDER, "DKEntries.csv")

    # --- 2. Load DK Entries ---
    if not os.path.exists(DK_FILE_PATH):
        print(f"ERROR: Could not find file at {DK_FILE_PATH}")
        return

    # Robust header detection
    print(f"Reading file: {DK_FILE_PATH}")
    header_row_index = 0
    with open(DK_FILE_PATH, 'r') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines[:50]):
        if "Position" in line and "Name + ID" in line:
            header_row_index = i
            break
            
    try:
        dk_df = pd.read_csv(DK_FILE_PATH, header=header_row_index)
        
        if 'Name' not in dk_df.columns:
            print("ERROR: Could not find 'Name' column.")
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
            match, score = process.extractOne(dk_name, valid_db_names)
            if score >= 90:
                final_names_to_query.append(match)

        final_names_to_query = list(set(final_names_to_query))
        print(f"Identified {len(final_names_to_query)} valid database players.")

        # --- 5. Create the View ---
        # Escape single quotes for SQL safety
        formatted_names = [name.replace("'", "''") for name in final_names_to_query]
        sql_names_string = "', '".join(formatted_names)
        
        # We drop the old view and recreate it with the CURRENT slate's players
        view_name = "vw_daily_slate"
        
        drop_view_sql = f"DROP VIEW IF EXISTS {view_name};"
        
        create_view_sql = f"""
        CREATE VIEW {view_name} AS
        SELECT 
            SEASON, PLAYER, TEAM, GP, GS, MPG, GSMPG, FPPG, GSFPPG, FPPM, GSFPPM, STDV_FPPG as STDV
        FROM 
            vw_player_averages_regular_season
        WHERE 
            (SEASON = '2024-25' AND GP >=20)
            OR SEASON = '2025-26'
            AND PLAYER IN ('{sql_names_string}')
        ORDER BY 
            TEAM, PLAYER, SEASON DESC;
        """

        with engine.connect() as connection:
            connection.execute(text(drop_view_sql))
            connection.execute(text(create_view_sql))
            connection.commit()
            
        print(f"SUCCESS: View '{view_name}' has been updated with {len(final_names_to_query)} players.")
        print("You can now query 'vw_daily_slate' directly from Excel.")

    except Exception as e:
        print(f"*** An error occurred: {e} ***")

if __name__ == "__main__":
    run_slate_averages_pipeline()