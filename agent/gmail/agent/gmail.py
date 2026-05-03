from __future__ import annotations
from tqdm import tqdm

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass(frozen=True)
class EmailHeader:
    message_id: str
    date_iso: str
    sender: str
    subject: str


def _load_creds(oauth_client_json: Path, token_json: Path) -> Credentials:
    creds: Optional[Credentials] = None
    if token_json.exists():
        creds = Credentials.from_authorized_user_file(str(token_json), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_json.parent.mkdir(parents=True, exist_ok=True)
        token_json.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if creds and creds.valid:
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client_json), SCOPES)
    creds = flow.run_local_server(port=0)
    token_json.parent.mkdir(parents=True, exist_ok=True)
    token_json.write_text(creds.to_json(), encoding="utf-8")
    return creds


def fetch_headers_last_12_months(
    oauth_client_json: Path,
    token_json: Path,
    user_id: str = "me",
    max_results: int = 500,
) -> List[EmailHeader]:
    creds = _load_creds(oauth_client_json, token_json)
    svc = build("gmail", "v1", credentials=creds)

    resp = svc.users().messages().list(
        userId=user_id,
        q="newer_than:12m",
        maxResults=max_results,
    ).execute()

    msgs = resp.get("messages", []) or []
    out: List[EmailHeader] = []

    for m in tqdm(msgs, desc="Fetching Gmail header", unit="email"):
        msg = svc.users().messages().get(
            userId=user_id,
            id=m["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()

        headers = {
            h["name"].lower(): h.get("value", "")
            for h in msg.get("payload", {}).get("headers", [])
        }

        out.append(
            EmailHeader(
                message_id=m["id"],
                date_iso=headers.get("date", ""),
                sender=headers.get("from", ""),
                subject=headers.get("subject", ""),
            )
        )

    return out
