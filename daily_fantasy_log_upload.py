# main.py
# Objectives:
# 1. Create a SQLite database for storing BigDataBall NBA datasets
# 2. Create a table for dfs logs and a table for player name standardization
# 3. Upload daily dfs logs - extracting only the logs which are not yet present in the dfs logs table
#    and consolidating player naming convention changes into the players dimension
import pandas as pd
from sqlalchemy import create_engine, text
import glob
import os

# --- 1. Configuration ---
# NOTE: The user has specified this absolute path.
BASE_PROJECT_PATH = "C:/Users/jrank/OneDrive/Documents/bigdataball"
NEW_FILES_FOLDER = os.path.join(BASE_PROJECT_PATH, "Daily_Fantasy_Logs")
PROCESSED_FOLDER = os.path.join(BASE_PROJECT_PATH, "Archived_Fantasy_Logs")
DB_PATH = os.path.join(BASE_PROJECT_PATH, "nba_fantasy_logs.db")

# Ensure the processed folder exists, creating it if necessary.
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

# Database Configuration
LOGS_TABLE_NAME = "fantasy_logs"
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
            print("First run: `fantasy_logs` table not found. Will create it.")
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
            new_data = pd.read_excel(file_path, header=1)
            cleaned_data = new_data.iloc[1:].dropna(how="all").copy()

            # --- NEW: Sanitize Column Names ---
            # Replace newlines and spaces with underscores, remove special chars, and convert to uppercase.
            # This makes column names database-friendly (e.g., "OWN\nTEAM" -> "OWN_TEAM").
            cleaned_data.columns = (
                cleaned_data.columns.str.replace("\n", "_")
                .str.replace(" ", "_")
                .str.replace(r"[^a-zA-Z0-9_]", "", regex=True)
                .str.upper()
            )

            # --- NEW: Drop and Rename Columns ---
            # Define columns to drop and the renaming map
            columns_to_drop = [
                "FANDUEL",
                "YAHOO",
                "FOR_FANDUEL_FULL_ROSTER_CONTESTS",
                "FOR_YAHOO_FULL_SLATE_CONTESTS",
                "FANDUEL1",
                "YAHOO1",
            ]
            rename_map = {
                "BIGDATABALL_DATASET": "SEASON_SEGMENT",
                "OWN_TEAM": "TEAM",
                "OPPONENT_TEAM": "OPPONENT",
                "STARTER_YN": "STARTED",
                "VENUE_RHN": "VENUE",
                "USAGE_RATE": "USAGE",
                "DAYS_REST__3SEASON_DEBUT_0_BACKTOBACK": "DAYS_REST",
                "DRAFTKINGS": "DK_POSITION",
                "FOR_DRAFTKINGS_CLASSIC_CONTESTS": "DK_SALARY",
                "DRAFTKINGS1": "DK_POINTS",
            }

            # Overwrite the original DATE column with a formatted version
            cleaned_data["DATE"] = pd.to_datetime(cleaned_data["DATE"]).dt.strftime(
                "%Y-%m-%d"
            )

            # Apply the renaming
            cleaned_data.rename(columns=rename_map, inplace=True)

            # Drop the unwanted columns, using errors='ignore' in case a column doesn't exist
            cleaned_data.drop(columns=columns_to_drop, inplace=True, errors="ignore")

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


if __name__ == "__main__":
    main()
