import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import config


def authenticate_google_drive():
    """
    Authenticates the user using the 'InstalledAppFlow' (3-Legged OAuth).
    Loads credentials explicitly from local files to avoid ADC conflicts.
    """
    creds = None

    # 1. Check for existing token.json (Persistence Strategy)
    if os.path.exists(config.TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.TOKEN_FILE, config.SCOPES)

    # 2. If no valid credentials, log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Auto-refresh if expired but refresh token exists
            print("Refreshing access token...")
            creds.refresh(Request())
        else:
            # Launch the browser for initial login
            print("No valid token found. Launching browser for authentication...")
            if not os.path.exists(config.CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Missing {config.CREDENTIALS_FILE}. Did you download it from GCP?"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                config.CREDENTIALS_FILE, config.SCOPES
            )
            # Run local server to capture the callback
            creds = flow.run_local_server(port=0)

        # 3. Save the new credentials for next time
        with open(config.TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds
