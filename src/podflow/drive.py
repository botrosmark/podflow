"""Google Drive API wrapper."""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from podflow.config import get_google_client_secret_path, get_google_token_path

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

CATEGORY_FOLDER_MAP = {
    "investing": "Investing",
    "tech": "Tech",
    "ai": "AI",
    "general": "General",
}


def get_credentials() -> Credentials:
    token_path = get_google_token_path()
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
    elif not creds or not creds.valid:
        raise RuntimeError(
            "No valid Google credentials. Run: podflow setup-drive"
        )

    return creds


def run_oauth_flow() -> Credentials:
    """Run the interactive OAuth consent flow."""
    client_secret_path = get_google_client_secret_path()
    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Google client secret not found at {client_secret_path}. "
            "Download it from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=8085)

    token_path = get_google_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    _save_token(creds, token_path)
    logger.info(f"Token saved to {token_path}")
    return creds


def _save_token(creds: Credentials, path: Path) -> None:
    path.write_text(creds.to_json())


def get_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def find_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    """Find a folder by name (under parent), or create it."""
    escaped_name = name.replace("'", "\\'")
    q = f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    logger.info(f"Created folder: {name}")
    return folder["id"]


def setup_folder_structure(root_folder_name: str) -> dict[str, dict[str, str]]:
    """Create the full Drive folder structure. Returns mapping of category -> {podcast_name: folder_id}."""
    service = get_drive_service()
    root_id = find_or_create_folder(service, root_folder_name)
    logger.info(f"Root folder: {root_folder_name} ({root_id})")

    from podflow.config import load_podcasts

    folder_map: dict[str, dict[str, str]] = {}
    podcasts = load_podcasts()

    for category, folder_name in CATEGORY_FOLDER_MAP.items():
        cat_id = find_or_create_folder(service, folder_name, root_id)
        folder_map[category] = {}

        for podcast in podcasts:
            if podcast.category == category:
                pod_id = find_or_create_folder(service, podcast.name, cat_id)
                folder_map[category][podcast.slug] = pod_id
                logger.info(f"  {folder_name}/{podcast.name} -> {pod_id}")

    return folder_map


def get_podcast_folder_id(service, root_folder_name: str, category: str, podcast_name: str) -> str:
    """Get the folder ID for a specific podcast."""
    root_id = find_or_create_folder(service, root_folder_name)
    cat_folder = CATEGORY_FOLDER_MAP.get(category, "General")
    cat_id = find_or_create_folder(service, cat_folder, root_id)
    return find_or_create_folder(service, podcast_name, cat_id)


def upload_markdown(
    service,
    content: str,
    filename: str,
    folder_id: str,
) -> dict:
    """Upload markdown content as a Google Doc. Returns {id, url}."""
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown")
    metadata = {
        "name": filename,
        "parents": [folder_id],
        "mimeType": "application/vnd.google-apps.document",
    }
    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return {"id": file["id"], "url": file.get("webViewLink", "")}


def download_file_content(service, file_id: str) -> str:
    """Download a non-Google-Doc file's content as text."""
    content = service.files().get_media(fileId=file_id).execute()
    return content.decode("utf-8")


def delete_file(service, file_id: str) -> None:
    """Delete a file from Google Drive."""
    service.files().delete(fileId=file_id).execute()
    logger.info(f"Deleted Drive file: {file_id}")
