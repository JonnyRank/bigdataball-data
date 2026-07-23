# main.py
# Objectives:
# 1. Create a SQLite database for storing BigDataBall NBA datasets
# 2. Create a table for dfs logs and a table for player name standardization
# 3. Upload daily dfs logs - extracting only the logs which are not yet present in the dfs logs table
#    and consolidating player naming convention changes into the players dimension
# 4. Re-create database views after data is loaded.
import pandas as pd
from sqlalchemy import create_engine, text, Integer
import glob
import os
import create_summary_tables
import export_slate_averages_vw
import export_playoffs_slate_averages_vw
import export_slate_averages_csv
import daily_player_upload
import drive_ingestion
import email_notifier
import mappings
import paths
from datetime import datetime


# --- 1. Configuration ---
BASE_DATA_PATH = paths.resolve_base_data_path()

# Define specific paths based on the Base Data Path
NEW_FILES_FOLDER = os.path.join(BASE_DATA_PATH, "Daily_Fantasy_Logs")
PROCESSED_FOLDER = os.path.join(BASE_DATA_PATH, "Archived_Fantasy_Logs")
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")

# Ensure the processed folder exists
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

# Database Configuration
LOGS_TABLE_NAME = "fantasy_logs"
PLAYERS_TABLE_NAME = "dim_players"
engine = create_engine(f"sqlite:///{DB_PATH}")


def ensure_unique_index():
    """Create the unique index on (PLAYER_ID, DATE) if the table exists.
    Called from initialize_database() (existing tables) and after to_sql()
    (first-run table creation), so the index is present from the very first insert.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{LOGS_TABLE_NAME}_player_date
                ON {LOGS_TABLE_NAME} ("PLAYER_ID", "DATE")
                """
                )
            )
    except Exception as e:
        if "no such table" in str(e):
            pass  # table not yet created; to_sql will create it, then we call this again
        else:
            raise


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
    ensure_unique_index()


def main():
    """
    Finds all new .xlsx files, processes them into the database ensuring no
    duplicate game logs are added, and moves them to an archive folder.
    Then runs the summary and slate export pipelines.
    """

    pipeline_errors = []

    # --- STEP 0: Run Google Drive Ingestion ---
    print("\n=== STARTING PIPELINE: GOOGLE DRIVE INGESTION ===")
    try:
        drive_ingestion.main()
    except Exception as e:
        error_msg = f"CRITICAL ERROR in Drive Ingestion: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
    print("=== GOOGLE DRIVE INGESTION COMPLETE ===\n")

    # --- STEP 1: Run Player Log Uploads (Box Scores) ---
    print("\n=== STARTING PIPELINE: PLAYER LOGS ===")
    player_logs_count = 0
    player_logs_overwritten = 0
    absence_rows_count = 0
    try:
        result = daily_player_upload.main()
        if isinstance(result, tuple):
            player_logs_count, player_logs_overwritten, absence_rows_count = result
        else:
            player_logs_count = result or 0
    except Exception as e:
        error_msg = f"CRITICAL ERROR in Player Upload: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)
    print("=== PLAYER LOGS COMPLETE ===\n")

    # --- STEP 2: Initialize DB for Fantasy Logs ---
    # ensure_unique_index() (via initialize_database) can raise on a pre-existing
    # (PLAYER_ID, DATE) duplicate in fantasy_logs. Record the failure like every
    # other stage so the run still reaches the summary/export steps and fires the
    # notification email, rather than crashing the orchestrator unhandled.
    try:
        initialize_database()
    except Exception as e:
        error_msg = f"CRITICAL ERROR in Fantasy DB Initialization: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

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
        print("No new files found to process. Skipping ingestion phase.")
    else:
        print(f"Found {len(files_to_process)} new file(s) to process...")

    # Initialize ONCE before the loop so keys added per file accumulate across files
    # processed in the same run (prevents re-inserting logs from an earlier file).
    existing_log_keys = set(existing_logs_df["log_key"]) if files_to_process else set()

    fantasy_logs_count = 0
    fantasy_logs_overwritten = 0
    fantasy_rows_dropped = 0
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

            # --- NEW: Standardize Player Names using Shared Mapping ---
            if "PLAYER" in cleaned_data.columns:
                # Identify names that are about to be changed for visibility
                changed_mask = cleaned_data["PLAYER"].isin(mappings.PLAYER_NAME_MAP)
                if changed_mask.any():
                    print(
                        f"  > Standardizing names: {cleaned_data.loc[changed_mask, 'PLAYER'].unique().tolist()}"
                    )
                cleaned_data["PLAYER"] = cleaned_data["PLAYER"].replace(
                    mappings.PLAYER_NAME_MAP
                )

            # --- End of new transformation section ---

            # --- NEW: Normalize ID columns to integers ---
            # Normalize ID columns to integers so fantasy_logs matches player_logs /
            # player_absences (which store PLAYER_ID / GAME_ID as INTEGER). Rows missing
            # an ID are not valid player-game logs -> drop them before casting, but NEVER
            # silently: a missing ID "can" happen and must be visible when it does.
            id_cols = [c for c in ("PLAYER_ID", "GAME_ID") if c in cleaned_data.columns]
            missing_mask = cleaned_data[id_cols].isna().any(axis=1)
            dropped = int(missing_mask.sum())
            if dropped:
                print(
                    f"  > WARNING: dropping {dropped} fantasy row(s) in {file_name} with a "
                    f"missing {id_cols} value (not a valid player-game log)."
                )
                fantasy_rows_dropped += dropped  # run-level counter, surfaced in the email (below)
                cleaned_data = cleaned_data.loc[~missing_mask]
            for c in id_cols:
                # Reject fractional IDs rather than silently truncating them: astype(int)
                # would turn a corrupt 12345.7 into 12345 (a different, valid-looking player).
                frac = cleaned_data[c][cleaned_data[c] % 1 != 0]
                if not frac.empty:
                    raise ValueError(
                        f"{c} has non-integer values (refusing to truncate): {frac.unique().tolist()}"
                    )
                cleaned_data[c] = cleaned_data[c].astype(int)

            # --- 4b. De-duplicate Logs ---
            # Create a unique key in both dataframes for comparison
            cleaned_data["log_key"] = (
                cleaned_data["PLAYER_ID"].astype(str) + "_" + cleaned_data["DATE"]
            )

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
                    )
                    truly_new_players_df_renamed.to_sql(
                        PLAYERS_TABLE_NAME, con=engine, if_exists="append", index=False
                    )

                # --- 4d. Load (to fantasy_logs) ---
                print(
                    f"Adding {len(truly_new_logs_df)} new game logs to {LOGS_TABLE_NAME}."
                )
                truly_new_logs_df.to_sql(
                    LOGS_TABLE_NAME,
                    con=engine,
                    if_exists="append",
                    index=False,
                    dtype={
                        c: Integer()
                        for c in ("PLAYER_ID", "GAME_ID")
                        if c in truly_new_logs_df.columns
                    },
                )
                ensure_unique_index()  # idempotent; creates index on first run
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

            # Check if we are overwriting an existing file
            is_overwrite = os.path.exists(destination_path)

            # Use replace to overwrite if the file already exists in the archive
            os.replace(file_path, destination_path)
            print(f"Successfully processed and moved {file_name}.")
            fantasy_logs_count += 1
            if is_overwrite:
                fantasy_logs_overwritten += 1

        except Exception as e:
            error_msg = f"ERROR processing {file_name}: {e}"
            print(f"\n*** {error_msg} ***")
            print("Script will stop. The failed file was NOT moved.")
            pipeline_errors.append(error_msg)
            break

    print("\n--- All new files processed. ---")

    print("\n--- Ingestion Phase Complete ---")

    # --- Run the summary and export pipeline automatically ---
    print("\nStarting automatic summary generation...")
    try:
        create_summary_tables.run_summary_pipeline()
        print("Summary generation complete.")
    except Exception as e:
        error_msg = f"ERROR in Summary Generation: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

    # --- Run the slate averages pipeline ---
    print("\nStarting slate view update...")
    unmatched_dk_players = []
    try:
        unmatched_dk_players = (
            export_slate_averages_vw.run_slate_averages_pipeline() or []
        )
        print("Slate view update complete.")
    except Exception as e:
        error_msg = f"ERROR in Slate View Update: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

    # --- Run the playoffs slate averages pipeline ---
    # The playoffs view is still rebuilt every run, but its unmatched-player result is
    # intentionally NOT used for the email warning / todo_mappings worklist — that
    # worklist tracks the regular-season slate. (During the regular season the playoffs
    # view is empty/stale and would flood the worklist with false positives.)
    print("\nStarting playoffs slate view update...")
    try:
        export_playoffs_slate_averages_vw.run_playoffs_slate_averages_pipeline()
        print("Playoffs slate view update complete.")
    except Exception as e:
        error_msg = f"ERROR in Playoffs Slate View Update: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

    # --- Run the slate CSV export ---
    print("\nStarting slate CSV export...")
    try:
        export_slate_averages_csv.run_slate_averages_smart_export()
        print("Slate CSV export complete.")
    except Exception as e:
        error_msg = f"ERROR in Slate CSV Export: {e}"
        print(f"*** {error_msg} ***")
        pipeline_errors.append(error_msg)

    print("\nAll pipelines complete.")

    # Get current date for subject line
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Send Notification ---
    if pipeline_errors:
        subject = f"BigDataBall Pipeline: COMPLETED WITH ERRORS [{date_str}]"
        body = "The pipeline ran but encountered the following errors:\n\n" + "\n".join(
            pipeline_errors
        )
        email_notifier.send_email_alert(subject, body)
    else:
        subject = f"BigDataBall Pipeline: SUCCESS [{date_str}]"
        body = (
            "The daily ingestion pipeline completed successfully with no errors.\n\n"
            f"Player Logs Processed: {player_logs_count} (Overwritten: {player_logs_overwritten})\n"
            f"Fantasy Logs Processed: {fantasy_logs_count} (Overwritten: {fantasy_logs_overwritten})\n"
            f"Fantasy Rows Dropped (missing PLAYER_ID/GAME_ID): {fantasy_rows_dropped}\n"
            f"Absence Rows Processed: {absence_rows_count}"
        )

        if fantasy_rows_dropped > 0:
            if " (With Warnings)" not in subject:
                subject += " (With Warnings)"
            body += "\n\n--- WARNING: Fantasy Rows Dropped ---\n"
            body += (
                f"{fantasy_rows_dropped} fantasy log row(s) were dropped this run because "
                "they were missing a PLAYER_ID or GAME_ID value (not valid player-game logs). "
                "See the console/log output for the affected file name(s)."
            )

        if unmatched_dk_players:
            if " (With Warnings)" not in subject:
                subject += " (With Warnings)"

            # --- NEW: Write to todo_mappings.txt ---
            todo_path = os.path.join(BASE_DATA_PATH, "todo_mappings.txt")
            try:
                # Check if file exists and has content to determine if we need a leading newline separator
                needs_newline = (
                    os.path.exists(todo_path) and os.path.getsize(todo_path) > 0
                )
                with open(todo_path, "a", encoding="utf-8") as f:
                    if needs_newline:
                        f.write("\n")
                    f.write(f"--- Unmatched Players: {date_str} ---\n")
                    for name in unmatched_dk_players:
                        f.write(f"{name}\n")
                print(f"  > Unmatched players appended to {todo_path}")
            except Exception as e:
                print(f"  > Error writing to todo_mappings.txt: {e}")

            body += "\n\n--- WARNING: Unmatched DraftKings Players ---\n"
            body += f"The following {len(unmatched_dk_players)} players in DKEntries.csv could not be matched to the database:\n"
            for name in unmatched_dk_players:
                body += f" - {name}\n"
            body += "\nPlease update mappings.py or check the source file."

        email_notifier.send_email_alert(subject, body)


if __name__ == "__main__":
    main()
