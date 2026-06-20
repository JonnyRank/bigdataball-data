import sqlite3
import os
import mappings
import paths

# --- Configuration: Match logic from main scripts ---
BASE_DATA_PATH = paths.resolve_base_data_path()

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")


def fix_player_names():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return

    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Define the tables and columns that may contain player names to be corrected.
    # NOTE: Table and column names are hard-coded here and not from user input,
    # so using them in f-strings for SQL is safe in this context.
    tables_to_patch = {
        "dim_players": "PLAYER_NAME",
        "fantasy_logs": "PLAYER",
        "player_logs": "PLAYER",
        "fantasy_averages": "PLAYER",
    }

    print("Starting retroactive player name correction across all relevant tables...")
    total_updates = 0

    for incorrect_name, correct_name in mappings.PLAYER_NAME_MAP.items():
        print(f"\n--- Applying mapping: '{incorrect_name}' -> '{correct_name}' ---")

        for table, column in tables_to_patch.items():
            try:
                # Check for records to update using parameter binding for safety
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                    (incorrect_name,),
                )
                count = cursor.fetchone()[0]

                if count > 0:
                    print(f"  > Found {count} record(s) in '{table}'. Updating...")
                    # Execute the update
                    cursor.execute(
                        f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                        (correct_name, incorrect_name),
                    )
                    total_updates += cursor.rowcount

            except sqlite3.OperationalError as e:
                # This handles cases where a table or column might not exist
                if "no such table" in str(e) or "no such column" in str(e):
                    print(f"  > Skipping '{table}': Table or column not found.")
                else:
                    # Re-raise other operational errors
                    raise e

    print("\n--- Patch Summary ---")
    if total_updates > 0:
        print(f"Committing {total_updates} total changes to the database.")
        conn.commit()
    else:
        print("No changes were needed.")

    conn.close()
    print("Database connection closed.")


if __name__ == "__main__":
    fix_player_names()
