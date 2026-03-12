"""Shared Google OAuth helper for Gmail and Calendar tools.

First run opens a browser for OAuth consent. Token is cached at ~/.hermit_crab/google_token.json.
"""

import os
from pathlib import Path

# Allow Google to return fewer scopes than requested
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
]

TOKEN_PATH = Path.home() / ".hermit_crab" / "google_token.json"
CLIENT_SECRET = Path.home() / ".config" / "gws" / "client_secret.json"


def get_credentials() -> Credentials:
    """Return valid Google OAuth credentials, refreshing or re-authing as needed."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        return creds

    # Need fresh auth — opens browser
    if not CLIENT_SECRET.exists():
        raise FileNotFoundError(
            f"OAuth client secret not found at {CLIENT_SECRET}. "
            "Run 'gws auth setup' first or place client_secret.json there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_token(creds)
    return creds


def _save_token(creds: Credentials):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
