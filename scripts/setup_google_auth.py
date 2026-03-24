#!/usr/bin/env python3
"""One-time Google OAuth consent flow.

Run this script to authenticate with Google Drive:
    python scripts/setup_google_auth.py

This will open a browser window for OAuth consent.
The token will be saved for reuse by podflow.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from podflow.drive import run_oauth_flow


def main():
    print("Starting Google OAuth flow...")
    print("A browser window will open for authentication.\n")
    creds = run_oauth_flow()
    print(f"\nAuthentication successful! Token saved.")
    print("You can now use 'podflow setup-drive' to create the folder structure.")


if __name__ == "__main__":
    main()
