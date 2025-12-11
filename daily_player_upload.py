# daily_player_log_upload.py
# Objectives:
# 1. Connect to SQLite database
# 2. Process new daily player logs (Excel) from 'Daily_Player_Logs'
# 3. Clean, renaming columns based on names.txt
# 4. Load into 'player_logs' table
# 5. Update 'dim_players' if new players are found
# 6. Archive processed files and run summary generation
import pandas as pd
from sqlalchemy import create_engine, text
import glob
import os

# --- 1. Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# HARDCODED PATHS FOR MIGRATION
# Check if Google Drive (G:) exists
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    # Fallback for non-synced machines
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")

# Define specific paths based on the Base Data Path
NEW_FILES_FOLDER = os.path.join(BASE_DATA_PATH, "Daily_Player_Logs")
PROCESSED_FOLDER = os.path.join(BASE_DATA_PATH, "Archived_Player_Logs")
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")

# Ensure the processed folder exists
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

# Database Configuration
LOGS_TABLE_NAME = "player_logs"
PLAYERS_TABLE_NAME = "dim_players"
engine = create_engine(f"sqlite:///{DB_PATH}")


def initialize_database():
    """Creates the dim_players table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
            CREATE TABLE IF NOT EXISTS {PLAYERS_TABLE_NAME} (
                "PLAYER_ID" INTEGER PRIMARY KEY,
                "PLAYER_NAME" TEXT
            );
            """
            )
        )
        # Also ensure the main logs table exists
        conn.commit()


def main():
    """
    Finds all new .xlsx files, processes them into the database ensuring no
    duplicate game logs are added, and moves them to an archive folder.
    """
    initialize_database()

    # --- Pre-load existing logs ---
    # Try to load the logs that are already in the database.
    # If the table doesn't exist (first run), create an empty DataFrame.
    try:
        existing_logs_df = pd.read_sql(
            f'SELECT DISTINCT "PLAYER_ID", "DATE" FROM {LOGS_TABLE_NAME}', engine
        )
        if not existing_logs_df.empty:
            print(f"Found {len(existing_logs_df)} existing logs in the database.")
            # Create the log_key from the loaded data
            existing_logs_df["log_key"] = (
                existing_logs_df["PLAYER_ID"].astype(str)
                + "_"
                + pd.to_datetime(existing_logs_df["DATE"]).dt.strftime("%Y-%m-%d")
            )
        else:
            # If the table exists but is empty, ensure the log_key column exists
            existing_logs_df["log_key"] = pd.Series(dtype="str")

    except Exception as e:
        if "no such table" in str(e):
            print(f"First run: `{LOGS_TABLE_NAME}` table not found. Will create it.")
            # Create an empty DataFrame with all necessary columns
            existing_logs_df = pd.DataFrame(columns=["PLAYER_ID", "DATE", "log_key"])
        else:
            # For any other database error, stop the script.
            print(f"A database error occurred: {e}")
            return

    # Sort the files to process them in chronological order, which is good practice.
    files_to_process = sorted(glob.glob(os.path.join(NEW_FILES_FOLDER, "*.xlsx")))

    if not files_to_process:
        print("No new files found to process.")
        return

    print(f"Found {len(files_to_process)} new file(s) to process...")

    for file_path in files_to_process:
        file_name = os.path.basename(file_path)
        print(f"--- Processing: {file_name} ---")

        try:
            # --- 4a. Extract & Transform ---
            new_data = pd.read_excel(file_path)
            # Since the header is on row 0, we don't need to skip any rows.
            # We just drop any rows that are completely empty.
            cleaned_data = new_data.dropna(how="all").copy()

            # --- NEW: Sanitize Column Names ---
            # Replace newlines and spaces with underscores, remove special chars, and convert to uppercase.
            # This makes column names database-friendly (e.g., "OWN\nTEAM" -> "OWN_TEAM").
            cleaned_data.columns = (
                cleaned_data.columns.str.replace("\n", "_")
                .str.replace("-", "_")  # Convert hyphens to underscores
                .str.replace(" ", "_")
                .str.replace(r"[^a-zA-Z0-9_]", "", regex=True)
                .str.upper()
            )

            # --- Rename Columns ---
            # Define columns renaming map

            rename_map = {
                "BIGDATABALL_DATASET": "SEASON_SEGMENT",
                "GAME_ID": "GAME_ID",
                "PLAYER_ID": "PLAYER_ID",  # No change needed
                "PLAYER__FULL_NAME": "PLAYER",  # From debug output
                "POSITION": "POSITION",
                "OWN__TEAM": "TEAM",  # From debug output
                "OPPONENT__TEAM": "OPPONENT",  # From debug output
                "VENUE_RHN": "VENUE",  # From debug output
                "STARTER_YN": "STARTED",
                "MIN": "MINUTES",
                "FG": "FG",
                "FGA": "FGA",
                "3P": "3P",  # From debug output
                "3PA": "3PA",  # From debug output
                "FT": "FT",
                "FTA": "FTA",
                "OR": "OREB",  # From debug output
                "DR": "DREB",  # From debug output
                "TOT": "TREB",  # From debug output
                "A": "AST",  # From debug output
                "PF": "PF",
                "ST": "STL",  # From debug output
                "TO": "TOV",  # From debug output
                "BL": "BLK",  # From debug output
                "PTS": "PTS",
                "USAGE__RATE_": "USAGE",  # From debug output
                "DAYS_REST": "DAYS_REST",
            }

            # Since the source column is 'DATE', we can format it directly after sanitization.
            cleaned_data["DATE"] = pd.to_datetime(cleaned_data["DATE"]).dt.strftime(
                "%Y-%m-%d"
            )

            # The debug print statement can now be removed.

            # Apply the renaming using the map
            cleaned_data.rename(columns=rename_map, inplace=True)

            # --- End of new transformation section ---

            # --- 4b. De-duplicate Logs ---
            # Create a unique key in both dataframes for comparison
            cleaned_data["log_key"] = (
                cleaned_data["PLAYER_ID"].astype(str) + "_" + cleaned_data["DATE"]
            )

            existing_log_keys = set(existing_logs_df["log_key"])

            # Filter for rows that are not already in the database
            truly_new_logs_df = cleaned_data[
                ~cleaned_data["log_key"].isin(existing_log_keys)
            ].drop(columns=["log_key"])

            if truly_new_logs_df.empty:
                print("No new game logs found in this file. Moving to archive.")
            else:
                # --- 4c. Learn New Players (from the original plan) ---
                new_players_df = truly_new_logs_df[
                    ["PLAYER_ID", "PLAYER"]
                ].drop_duplicates(subset=["PLAYER_ID"])

                existing_players_df = pd.read_sql(
                    f'SELECT "PLAYER_ID" FROM {PLAYERS_TABLE_NAME}', engine
                )
                existing_ids = set(existing_players_df["PLAYER_ID"])

                truly_new_players_df_for_dim = new_players_df.loc[
                    ~new_players_df["PLAYER_ID"].isin(existing_ids)
                ]

                if not truly_new_players_df_for_dim.empty:
                    print(
                        f"Adding {len(truly_new_players_df_for_dim)} new players to {PLAYERS_TABLE_NAME}..."
                    )
                    truly_new_players_df_renamed = truly_new_players_df_for_dim.rename(
                        columns={"PLAYER": "PLAYER_NAME"}
                    ).rename(columns={"PLAYER_ID": "PLAYER_ID"})
                    truly_new_players_df_renamed.to_sql(
                        PLAYERS_TABLE_NAME, con=engine, if_exists="append", index=False
                    )

                # --- 4d. Load (to fantasy_logs) ---
                print(
                    f"Adding {len(truly_new_logs_df)} new game logs to {LOGS_TABLE_NAME}."
                )
                truly_new_logs_df.to_sql(
                    LOGS_TABLE_NAME, con=engine, if_exists="append", index=False
                )
                # --- Crucial Update ---
                # After adding new logs to the DB, we must also add their keys
                # to our in-memory set to prevent them from being added again
                # when processing the next (cumulative) file in the same run.
                newly_added_keys = set(
                    truly_new_logs_df["PLAYER_ID"].astype(str)
                    + "_"
                    + truly_new_logs_df["DATE"]
                )
                existing_log_keys.update(newly_added_keys)

            # --- 4e. Move File on Success ---
            destination_path = os.path.join(PROCESSED_FOLDER, file_name)
            os.rename(file_path, destination_path)
            print(f"Successfully processed and moved {file_name}.")

        except Exception as e:
            print(f"\n*** ERROR processing {file_name}: {e} ***")
            print("Script will stop. The failed file was NOT moved.")
            break

    print("\n--- All new files processed. ---")

    # --- Run the summary and export pipeline automatically ---
    # print("\nStarting automatic summary generation...")
    # create_summary_tables.run_summary_pipeline()
    # print("\nAutomatic summary generation complete.")


if __name__ == "__main__":
    main()
