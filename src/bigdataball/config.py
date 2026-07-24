import os
from dotenv import load_dotenv

load_dotenv()

# Base directory for downloads
BASE_DOWNLOAD_DIR = r"G:\My Drive\Documents\bigdataball"

# DATASET_JOBS: A list of dictionaries defining what to download and where.
DATASET_JOBS = [
    {
        "name": "DFS Feed",
        "drive_folder_id": os.getenv("DRIVE_FOLDER_ID_DFS"),
        "file_match": "-dfs-feed.xlsx",  # Substring to match in filename
        "local_dest": os.path.join(BASE_DOWNLOAD_DIR, "Daily_Fantasy_Logs"),
    },
    {
        # Example: Player Box Scores
        "name": "Player Feed",
        "drive_folder_id": os.getenv("DRIVE_FOLDER_ID_PLAYER"),
        "file_match": "season-player-feed.xlsx",
        "local_dest": os.path.join(BASE_DOWNLOAD_DIR, "Daily_Player_Logs"),
    },
]

# Path to credential files
CREDENTIALS_FILE = "client_secrets.json"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Email Notification Settings
EMAIL_ENABLED = True  # Set to False to disable temporarily
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
