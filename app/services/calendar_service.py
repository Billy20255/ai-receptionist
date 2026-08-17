"""
Google Calendar free/busy + booking. Kept as a thin wrapper so this is easy
to swap for GHL's native calendar later if/when the client moves to a GHL
snapshot (per the implementation spec's Phase 3) — nothing else in this
codebase needs to know which calendar backend is in use.
"""
from __future__ import annotations

import datetime as dt
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_client():
    if not os.path.exists(settings.google_service_account_json_path):
        return None  # not configured yet — callers should handle None
    creds = service_account.Credentials.from_service_account_file(
        settings.google_service_account_json_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def find_next_available_slot(
    duration_minutes: int = 30, search_days: int = 5
) -> dt.datetime | None:
    """Returns the start time of the next open slot, or None if the
    calendar isn't configured / nothing found in the search window."""
    service = _get_calendar_client()
    if service is None:
        return None

    now = dt.datetime.utcnow()
    window_end = now + dt.timedelta(days=search_days)

    body = {
        "timeMin": now.isoformat() + "Z",
        "timeMax": window_end.isoformat() + "Z",
        "items": [{"id": settings.google_calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy_blocks = result["calendars"][settings.google_calendar_id]["busy"]

    # Naive slot search: walk forward in duration_minutes increments during
    # business hours (9am-5pm) and return the first slot with no overlap.
    cursor = now.replace(minute=0, second=0, microsecond=0)
    while cursor < window_end:
        if 9 <= cursor.hour < 17:
            slot_end = cursor + dt.timedelta(minutes=duration_minutes)
            overlaps = any(
                cursor < dt.datetime.fromisoformat(b["end"].replace("Z", ""))
                and slot_end > dt.datetime.fromisoformat(b["start"].replace("Z", ""))
                for b in busy_blocks
            )
            if not overlaps:
                return cursor
        cursor += dt.timedelta(minutes=duration_minutes)
    return None


def book_slot(start_time: dt.datetime, summary: str, description: str, duration_minutes: int = 30) -> str | None:
    """Books the event, returns the calendar event ID, or None if calendar
    isn't configured (caller should fall back to 'we'll call you to confirm
    a time' in that case rather than failing the call)."""
    service = _get_calendar_client()
    if service is None:
        return None

    end_time = start_time + dt.timedelta(minutes=duration_minutes)
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "America/New_York"},
    }
    created = service.events().insert(calendarId=settings.google_calendar_id, body=event).execute()
    return created.get("id")
