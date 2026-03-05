from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

AUTOMATED_SENDER_RE = re.compile(
    r"(?:^|[\W_])(no-?reply|do-?not-?reply|unsubscribe|mailer-daemon|notifications?)(?:$|[\W_])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PendingEmail:
    thread_id: str
    subject: str
    last_inbound_timestamp: str
    participants: list[str]


@dataclass(frozen=True)
class EventItem:
    source: str
    title: str
    start: datetime
    end: datetime
    attendees: list[str]


def _load_creds(oauth_client_json: Path, token_json: Path, scopes: list[str]) -> Credentials:
    creds: Optional[Credentials] = None
    if token_json.exists():
        creds = Credentials.from_authorized_user_file(str(token_json), scopes)

    if creds and creds.valid and creds.has_scopes(scopes):
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if creds.has_scopes(scopes):
            token_json.parent.mkdir(parents=True, exist_ok=True)
            token_json.write_text(creds.to_json(), encoding="utf-8")
            return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client_json), scopes)
    creds = flow.run_local_server(port=0)
    token_json.parent.mkdir(parents=True, exist_ok=True)
    token_json.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _header_map(message: dict[str, Any]) -> dict[str, str]:
    return {
        h.get("name", "").lower(): h.get("value", "")
        for h in message.get("payload", {}).get("headers", [])
    }


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_emails(value: str) -> list[str]:
    out: list[str] = []
    for _, addr in getaddresses([value]):
        email = addr.strip().lower()
        if email:
            out.append(email)
    return out


def _is_automated_sender(sender_header: str) -> bool:
    return bool(AUTOMATED_SENDER_RE.search(sender_header))


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_from_google(value: str) -> datetime:
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    parsed_date = datetime.fromisoformat(value).date()
    return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)


def _normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def _find_col_idx(headers: list[str], candidates: list[str]) -> int:
    normalized = [_normalize_header(h) for h in headers]
    for candidate in candidates:
        cand = _normalize_header(candidate)
        if cand in normalized:
            return normalized.index(cand)
    return -1


def _parse_sheet_date(value: str) -> Optional[date]:
    v = value.strip()
    if not v:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", v):
        serial = int(float(v))
        return date(1899, 12, 30) + timedelta(days=serial)

    fmts = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _parse_sheet_time(value: str) -> Optional[time]:
    v = value.strip()
    if not v:
        return None
    fmts = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p"]
    for fmt in fmts:
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            continue
    return None


def _next_week_bounds(today: date) -> tuple[date, date]:
    days_to_next_monday = 7 - today.weekday()
    monday = today + timedelta(days=days_to_next_monday)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _fetch_pending_emails(
    gmail_svc: Any,
    lookback_days: int,
    user_email: str,
) -> list[PendingEmail]:
    pending: list[PendingEmail] = []
    page_token: Optional[str] = None
    query = f"newer_than:{lookback_days}d"

    while True:
        resp = gmail_svc.users().threads().list(
            userId="me",
            q=query,
            maxResults=100,
            pageToken=page_token,
        ).execute()
        threads = resp.get("threads", []) or []
        for thread in threads:
            thread_data = gmail_svc.users().threads().get(
                userId="me",
                id=thread["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Cc", "Date", "Subject"],
            ).execute()
            messages = thread_data.get("messages", []) or []

            latest_inbound: Optional[datetime] = None
            latest_outbound: Optional[datetime] = None
            participants: set[str] = set()
            subject = ""

            for m in messages:
                headers = _header_map(m)
                from_header = headers.get("from", "")
                if not subject:
                    subject = headers.get("subject", "")

                msg_dt = _parse_dt(headers.get("date", ""))
                sender_emails = _extract_emails(from_header)
                sender_email = sender_emails[0] if sender_emails else from_header.strip().lower()
                automated = _is_automated_sender(from_header)

                for header_name in ("from", "to", "cc"):
                    for email in _extract_emails(headers.get(header_name, "")):
                        if email != user_email and not _is_automated_sender(email):
                            participants.add(email)

                if automated or msg_dt is None:
                    continue

                if sender_email == user_email:
                    if latest_outbound is None or msg_dt > latest_outbound:
                        latest_outbound = msg_dt
                else:
                    if latest_inbound is None or msg_dt > latest_inbound:
                        latest_inbound = msg_dt

            if latest_inbound and (latest_outbound is None or latest_inbound > latest_outbound):
                pending.append(
                    PendingEmail(
                        thread_id=thread["id"],
                        subject=subject,
                        last_inbound_timestamp=_iso_z(latest_inbound),
                        participants=sorted(participants),
                    )
                )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    pending.sort(key=lambda x: x.last_inbound_timestamp, reverse=True)
    return pending


def _fetch_calendar_events(calendar_svc: Any, calendar_id: str) -> list[EventItem]:
    start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=8)
    events_resp = calendar_svc.events().list(
        calendarId=calendar_id,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = events_resp.get("items", []) or []

    out: list[EventItem] = []
    for ev in events:
        start_raw = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end_raw = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        if not start_raw or not end_raw:
            continue
        attendees = [
            a.get("email", "")
            for a in (ev.get("attendees", []) or [])
            if a.get("email")
        ]
        out.append(
            EventItem(
                source="calendar",
                title=ev.get("summary", "(untitled)"),
                start=_date_from_google(start_raw),
                end=_date_from_google(end_raw),
                attendees=sorted(set(attendees)),
            )
        )
    return out


def _fetch_sheet_assignments(sheets_svc: Any, spreadsheet_id: str, assignee: str) -> list[EventItem]:
    values_resp = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="A:Z",
    ).execute()
    rows = values_resp.get("values", []) or []
    if not rows:
        return []

    headers = rows[0]
    assignee_idx = _find_col_idx(headers, ["assignee", "owner"])
    date_idx = _find_col_idx(headers, ["date", "meeting_date"])
    time_idx = _find_col_idx(headers, ["time", "start_time"])
    meeting_idx = _find_col_idx(headers, ["meeting name", "meeting", "title", "event"])
    if assignee_idx < 0 or date_idx < 0:
        return []

    today = date.today()
    week_start, week_end = _next_week_bounds(today)
    out: list[EventItem] = []

    for row in rows[1:]:
        row_assignee = row[assignee_idx].strip() if assignee_idx < len(row) else ""
        if row_assignee.lower() != assignee.lower():
            continue
        row_date = row[date_idx].strip() if date_idx < len(row) else ""
        parsed_date = _parse_sheet_date(row_date)
        if not parsed_date or not (week_start <= parsed_date <= week_end):
            continue

        row_time = row[time_idx].strip() if time_idx >= 0 and time_idx < len(row) else ""
        parsed_time = _parse_sheet_time(row_time) or time(hour=9, minute=0)
        start_dt = datetime.combine(parsed_date, parsed_time, tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(minutes=30)
        title = (
            row[meeting_idx].strip()
            if meeting_idx >= 0 and meeting_idx < len(row) and row[meeting_idx].strip()
            else "Sheet meeting"
        )
        out.append(
            EventItem(
                source="sheet",
                title=title,
                start=start_dt,
                end=end_dt,
                attendees=[],
            )
        )
    return out


def _merge_schedule(events: list[EventItem]) -> list[dict[str, Any]]:
    merged = sorted(events, key=lambda x: x.start)
    out: list[dict[str, Any]] = []
    latest_end: Optional[datetime] = None
    for ev in merged:
        overlap = latest_end is not None and ev.start < latest_end
        latest_end = ev.end if latest_end is None else max(latest_end, ev.end)
        out.append(
            {
                "source": ev.source,
                "title": ev.title,
                "start": _iso_z(ev.start),
                "end": _iso_z(ev.end),
                "attendees": ev.attendees,
                "overlap": overlap,
            }
        )
    return out


def run_gmail_briefing(
    oauth_client_json: Path,
    token_json: Path,
    lookback_days: int,
    spreadsheet_id: str,
    calendar_id: str,
    assignee: str,
    out_path: Path,
) -> Path:
    creds = _load_creds(oauth_client_json=oauth_client_json, token_json=token_json, scopes=SCOPES)
    gmail_svc = build("gmail", "v1", credentials=creds)
    calendar_svc = build("calendar", "v3", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)

    profile = gmail_svc.users().getProfile(userId="me").execute()
    user_email = (profile.get("emailAddress", "") or "").lower()

    pending_emails = _fetch_pending_emails(
        gmail_svc=gmail_svc,
        lookback_days=lookback_days,
        user_email=user_email,
    )
    calendar_events = _fetch_calendar_events(calendar_svc=calendar_svc, calendar_id=calendar_id)
    sheet_events = _fetch_sheet_assignments(
        sheets_svc=sheets_svc,
        spreadsheet_id=spreadsheet_id,
        assignee=assignee,
    )
    schedule = _merge_schedule(calendar_events + sheet_events)

    today = date.today()
    tomorrow = today + timedelta(days=1)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    daily_events = [e for e in schedule if datetime.fromisoformat(e["start"].replace("Z", "+00:00")).date() == today]
    tomorrow_events = [e for e in schedule if datetime.fromisoformat(e["start"].replace("Z", "+00:00")).date() == tomorrow]
    stale_pending = [
        p
        for p in pending_emails
        if datetime.fromisoformat(p.last_inbound_timestamp.replace("Z", "+00:00")) <= stale_cutoff
    ]

    payload = {
        "run_at": _iso_z(datetime.now(timezone.utc)),
        "inputs": {
            "lookback_days": lookback_days,
            "spreadsheet_id": spreadsheet_id,
            "calendar_id": calendar_id,
            "assignee": assignee,
        },
        "pending_emails": [
            {
                "thread_id": p.thread_id,
                "subject": p.subject,
                "last_inbound_timestamp": p.last_inbound_timestamp,
                "participants": p.participants,
            }
            for p in pending_emails
        ],
        "calendar_events": [
            {
                "title": e.title,
                "start": _iso_z(e.start),
                "end": _iso_z(e.end),
                "attendees": e.attendees,
            }
            for e in calendar_events
        ],
        "next_week_UB_assignments": [
            {
                "date": e.start.date().isoformat(),
                "time": e.start.time().strftime("%H:%M"),
                "meeting_name": e.title,
            }
            for e in sheet_events
        ],
        "schedule": schedule,
        "notifications": {
            "daily": {
                "pending_emails": [
                    {
                        "thread_id": p.thread_id,
                        "subject": p.subject,
                        "last_inbound_timestamp": p.last_inbound_timestamp,
                    }
                    for p in pending_emails
                ],
                "today_events": daily_events,
                "tomorrow_events": tomorrow_events,
            },
            "weekly_friday": {
                "next_week_UB_assignments": [
                    {
                        "date": e.start.date().isoformat(),
                        "time": e.start.time().strftime("%H:%M"),
                        "meeting_name": e.title,
                    }
                    for e in sheet_events
                ],
                "pending_emails_older_than_lookback_days": [
                    {
                        "thread_id": p.thread_id,
                        "subject": p.subject,
                        "last_inbound_timestamp": p.last_inbound_timestamp,
                    }
                    for p in stale_pending
                ],
            },
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
