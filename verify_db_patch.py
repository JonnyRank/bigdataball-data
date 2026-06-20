import sqlite3
import os
import mappings
import paths

# --- Configuration ---
BASE_DATA_PATH = paths.resolve_base_data_path()

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")


def verify_patch():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tables_to_check = {
        "dim_players": "PLAYER_NAME",
        "fantasy_logs": "PLAYER",
        "player_logs": "PLAYER",
        "fantasy_averages": "PLAYER",
    }

    print("Verifying updated player names in the database...\n")
    print(f"{'Target Name':<22} | {'Table':<20} | {'Record Count'}")
    print("-" * 65)

    # We only care about checking the correct_name (the target)
    for incorrect_name, correct_name in mappings.PLAYER_NAME_MAP.items():
        for table, column in tables_to_check.items():
            try:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (correct_name,)
                )
                count = cursor.fetchone()[0]

                if count > 0:
                    print(f"{correct_name:<22} | {table:<20} | {count}")
            except sqlite3.OperationalError:
                pass  # Skip if a table or column doesn't exist yet

    conn.close()


if __name__ == "__main__":
    verify_patch()
