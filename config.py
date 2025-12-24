import os

# Base directory for downloads
BASE_DOWNLOAD_DIR = r"G:\My Drive\Documents\bigdataball"

# DATASET_JOBS: A list of dictionaries defining what to download and where.
DATASET_JOBS = [
    {
        "name": "DFS Feed",
        "drive_folder_id": "1AKiQPCB9rmbroGgpSqNUW2ui6e9_2mEW",
        "file_match": "-dfs-feed.xlsx",  # Substring to match in filename
        "local_dest": os.path.join(BASE_DOWNLOAD_DIR, "Daily_Fantasy_Logs"),
    },
    {
        # Example: Player Box Scores
        "name": "Player Feed",
        "drive_folder_id": "1K0ClOAbKTSzCxfJIQZ8rkA_Zu7maENHX",
        "file_match": "season-player-feed.xlsx",
        "local_dest": os.path.join(BASE_DOWNLOAD_DIR, "Daily_Player_Logs"),
    },
]

# Path to credential files
CREDENTIALS_FILE = "client_secrets.json"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
