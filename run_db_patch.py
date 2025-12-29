import sqlite3
import os

# --- Configuration: Match logic from main scripts ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Check if Google Drive (G:) exists
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    # Fallback for non-synced machines (local Data folder)
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")

DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")


def fix_player_names():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        return

    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Checking for 'GG Jackson' in dim_players...")

    # Check how many records match before updating
    cursor.execute("SELECT COUNT(*) FROM dim_players WHERE PLAYER_NAME = 'GG Jackson'")
    count = cursor.fetchone()[0]

    if count > 0:
        print(f"Found {count} record(s). Updating to 'Gregory Jackson'...")
        # Execute the update
        cursor.execute(
            "UPDATE dim_players SET PLAYER_NAME = 'Gregory Jackson' WHERE PLAYER_NAME = 'GG Jackson'"
        )
        conn.commit()
        print("Update complete.")
    else:
        print("No records found for 'GG Jackson'. He might already be updated.")

    conn.close()


if __name__ == "__main__":
    fix_player_names()
