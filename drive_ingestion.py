import io
import os
import googleapiclient.discovery
from googleapiclient.http import MediaIoBaseDownload
from auth_manager import authenticate_google_drive
import config


def get_drive_service():
    """Builds the Drive API service using our custom auth manager."""
    creds = authenticate_google_drive()
    return googleapiclient.discovery.build("drive", "v3", credentials=creds)


def find_latest_file(service, folder_id, file_match):
    """
    Queries Google Drive for files in a specific folder matching a name pattern.
    Returns the file metadata for the alphabetically last (latest) file.
    """
    query = (
        f"'{folder_id}' in parents and name contains '{file_match}' and trashed = false"
    )

    # supportsAllDrives=True is REQUIRED for Shared Drives/Folders
    results = (
        service.files()
        .list(
            q=query,
            orderBy="createdTime",  # Sort by creation time to handle date rollovers (e.g. 12-31 vs 01-01)
            fields="files(id, name, createdTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    items = results.get("files", [])

    if not items:
        return None

    # Python sort to ensure we get the last one chronologically (Latest)
    # ISO timestamps (createdTime) sort correctly as strings
    latest_file = sorted(items, key=lambda x: x["createdTime"])[-1]
    return latest_file


def download_file(service, file_id, file_name, local_dest):
    """Downloads a file from Drive to the local destination."""

    # Ensure directory exists
    if not os.path.exists(local_dest):
        os.makedirs(local_dest)

    file_path = os.path.join(local_dest, file_name)

    # Check if file already exists to avoid re-downloading
    if os.path.exists(file_path):
        print(f"  [Skipping] {file_name} already exists.")
        return

    print(f"  [Downloading] {file_name}...")
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while done is False:
        status, done = downloader.next_chunk()
        # Optional: Print progress if needed
        # print(f"Download {int(status.progress() * 100)}%.")

    print(f"  [Success] Saved to {file_path}")


def main():
    print("--- Starting NBA Data Ingestion ---")

    # We removed the try/except block here so errors bubble up to the main pipeline
    service = get_drive_service()

    for job in config.DATASET_JOBS:
        print(f"\nProcessing Job: {job['name']}")

        latest_file = find_latest_file(
            service, job["drive_folder_id"], job["file_match"]
        )

        if latest_file:
            print(f"  Found latest file: {latest_file['name']}")
            download_file(
                service, latest_file["id"], latest_file["name"], job["local_dest"]
            )
        else:
            print(f"  No files found matching '{job['file_match']}' in folder.")


if __name__ == "__main__":
    main()
