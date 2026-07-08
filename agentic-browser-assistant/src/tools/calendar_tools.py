# Google Calendar API tools
"""
calendar_tools.py

Google Calendar integration helpers built on `google-api-python-client`.

Provides a `CalendarTools` class with methods to:
    - scan for free time blocks              (get_free_slots)
    - create calendar events                 (add_event)
    - list upcoming events                   (list_events)
    - check for scheduling conflicts         (check_conflicts)

Also includes standalone helper functions for turning natural-language
date/time expressions (e.g. "next Thursday afternoon", "tomorrow at 3pm")
into ISO 8601 strings suitable for the Calendar API.

Setup
-----
1. Install dependencies:
       pip install google-api-python-client google-auth-httplib2 \
                   google-auth-oauthlib dateparser --break-system-packages

2. Create OAuth 2.0 credentials in the Google Cloud Console (Desktop app
   type) and download the `credentials.json` file.

3. On first run, `CalendarTools` will open a browser window for the user
   to authorize access, then cache a `token.json` file for subsequent runs.

Example
-------
    from calendar_tools import CalendarTools, parse_natural_datetime

    cal = CalendarTools()

    start, end = parse_natural_datetime("next Thursday afternoon")
    free_slots = cal.get_free_slots(start, end)

    cal.add_event(
        summary="Design review",
        start="2026-07-10T14:00:00",
        end="2026-07-10T15:00:00",
        description="Walk through the new mockups",
    )
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import List, Optional, Tuple, Union

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Missing Google API client libraries. Install them with:\n"
        "    pip install google-api-python-client google-auth-httplib2 "
        "google-auth-oauthlib --break-system-packages"
    ) from exc

try:
    import dateparser
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Missing 'dateparser'. Install it with:\n"
        "    pip install dateparser --break-system-packages"
    ) from exc


# --------------------------------------------------------------------------- #
# Natural-language date/time parsing helpers
# --------------------------------------------------------------------------- #

# Rough default hour ranges for time-of-day words that dateparser doesn't
# always resolve to a specific hour on its own.
_TIME_OF_DAY_DEFAULTS = {
    "morning": (9, 0),
    "afternoon": (14, 0),
    "evening": (18, 0),
    "night": (20, 0),
    "noon": (12, 0),
    "midnight": (0, 0),
}

_TIME_OF_DAY_PATTERN = re.compile(
    r"\b(morning|afternoon|evening|night|noon|midnight)\b", re.IGNORECASE
)

# How long a "block" implied by a time-of-day word should span, in hours.
_TIME_OF_DAY_SPAN_HOURS = 3

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# Matches an optional qualifier ("next"/"this"/"coming") followed by a
# weekday name, e.g. "next Thursday", "this Monday", "Friday".
_WEEKDAY_PATTERN = re.compile(
    r"\b(?:(next|this|coming)\s+)?(" + "|".join(_WEEKDAYS.keys()) + r")\b",
    re.IGNORECASE,
)


def _resolve_weekday(
    qualifier: Optional[str], weekday_name: str, base_date: dt.datetime
) -> dt.date:
    """
    Resolve a (qualifier, weekday) pair such as ("next", "thursday") to a
    concrete date, relative to `base_date`.

    dateparser's handling of "next <weekday>" is inconsistent across
    versions/locales, so this is resolved manually for reliability:
        - "next <weekday>"          -> the occurrence in the following week
                                        (skips today even if it matches)
        - "this <weekday>" / bare   -> the closest upcoming occurrence,
                                        including today
    """
    target_idx = _WEEKDAYS[weekday_name.lower()]
    today = base_date.date()
    days_ahead = (target_idx - today.weekday()) % 7

    if (qualifier or "").lower() == "next":
        if days_ahead == 0:
            days_ahead = 7

    return today + dt.timedelta(days=days_ahead)


def _extract_date_and_remainder(
    text: str, base_date: dt.datetime
) -> Tuple[Optional[dt.date], str]:
    """
    Look for a "[next/this/coming] <weekday>" phrase in `text` and, if
    found, resolve it to a concrete date and return the leftover text
    (e.g. a time-of-day word) for further parsing.

    Returns (None, text) if no weekday phrase is found, signalling that
    the caller should fall back to parsing `text` as a whole.
    """
    match = _WEEKDAY_PATTERN.search(text)
    if not match:
        return None, text

    qualifier, weekday_name = match.groups()
    resolved_date = _resolve_weekday(qualifier, weekday_name, base_date)
    remainder = (text[: match.start()] + " " + text[match.end() :]).strip()
    return resolved_date, remainder


def parse_natural_datetime(
    text: str,
    *,
    base_date: Optional[dt.datetime] = None,
    timezone: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Parse a natural-language date/time expression into an (start, end) ISO
    8601 tuple.

    Handles phrases like:
        "next Thursday afternoon"  -> (Thursday 14:00, Thursday 17:00)
        "tomorrow at 3pm"          -> (tomorrow 15:00, tomorrow 16:00)
        "July 10th"                -> (July 10 00:00, July 10 23:59:59)

    If the phrase contains an explicit time (e.g. "3pm", "15:00"), the
    returned window is a 1-hour block starting at that time. If the phrase
    only contains a time-of-day word (morning/afternoon/evening/night), the
    window spans a few hours matching that part of the day. If only a date
    is given, the window spans the whole day.

    Parameters
    ----------
    text:
        The natural-language date/time string.
    base_date:
        The date to resolve relative expressions against. Defaults to now.
    timezone:
        An IANA timezone name (e.g. "America/New_York") to localize the
        result to. If omitted, naive local time is used.

    Returns
    -------
    (start_iso, end_iso): Tuple[str, str]
    """
    base_date = base_date or dt.datetime.now()

    resolved_date, remainder = _extract_date_and_remainder(text, base_date)

    settings = {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": bool(timezone),
    }
    if timezone:
        settings["TIMEZONE"] = timezone
        settings["TO_TIMEZONE"] = timezone

    if resolved_date is not None:
        # Weekday phrase was found and resolved manually; only the
        # remainder (e.g. a time-of-day word or clock time) still needs
        # dateparser, anchored to the resolved date.
        settings["RELATIVE_BASE"] = dt.datetime.combine(resolved_date, dt.time(0, 0))

        if remainder and (
            _TIME_OF_DAY_PATTERN.search(remainder) or _has_explicit_hour(remainder)
        ):
            parsed = dateparser.parse(remainder, settings=settings)
            if parsed is None:
                parsed = dt.datetime.combine(resolved_date, dt.time(0, 0))
            else:
                # Force the date component to the resolved weekday; keep
                # whatever time-of-day dateparser extracted.
                parsed = parsed.replace(
                    year=resolved_date.year,
                    month=resolved_date.month,
                    day=resolved_date.day,
                )
        else:
            parsed = dt.datetime.combine(resolved_date, dt.time(0, 0))
    else:
        settings["RELATIVE_BASE"] = base_date
        parsed = dateparser.parse(text, settings=settings)
        if parsed is None:
            raise ValueError(f"Could not parse date/time expression: {text!r}")

    tod_match = _TIME_OF_DAY_PATTERN.search(text)
    has_explicit_clock_time = bool(
        re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)?\b", text, re.IGNORECASE)
        and re.search(r"\d", text)
        and not tod_match
    )

    if tod_match and not _has_explicit_hour(text):
        # Only a time-of-day word was given (e.g. "afternoon") -> use a
        # default hour and span a multi-hour block.
        word = tod_match.group(1).lower()
        hour, minute = _TIME_OF_DAY_DEFAULTS[word]
        start_dt = parsed.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end_dt = start_dt + dt.timedelta(hours=_TIME_OF_DAY_SPAN_HOURS)
    elif has_explicit_clock_time or _has_explicit_hour(text):
        # An explicit clock time was given -> 1-hour block.
        start_dt = parsed
        end_dt = start_dt + dt.timedelta(hours=1)
    else:
        # Only a date was given -> span the whole day.
        start_dt = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=0)

    return start_dt.isoformat(), end_dt.isoformat()


def _has_explicit_hour(text: str) -> bool:
    """Detect an explicit clock time like '3pm', '15:00', '3:30 pm'."""
    return bool(re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", text, re.IGNORECASE)) or bool(
        re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
    )


def to_iso8601(value: Union[str, dt.datetime]) -> str:
    """
    Normalize a datetime-like input into an ISO 8601 string.

    Accepts either a `datetime` object, an already-ISO string, or a
    natural-language expression (delegated to `parse_natural_datetime`,
    using only the start of the resulting window).
    """
    if isinstance(value, dt.datetime):
        return value.isoformat()

    # Try strict ISO parsing first.
    try:
        return dt.datetime.fromisoformat(value).isoformat()
    except ValueError:
        pass

    start_iso, _ = parse_natural_datetime(value)
    return start_iso


# --------------------------------------------------------------------------- #
# CalendarTools
# --------------------------------------------------------------------------- #

class CalendarTools:
    """Wrapper around the Google Calendar API for common scheduling tasks."""

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
        calendar_id: str = "primary",
        timezone: str = "UTC",
    ):
        """
        Parameters
        ----------
        credentials_path:
            Path to the OAuth client secrets JSON downloaded from Google
            Cloud Console.
        token_path:
            Path where the user's authorized token is cached between runs.
        calendar_id:
            The calendar to operate on. Defaults to the user's primary
            calendar.
        timezone:
            IANA timezone name used for created events and free/busy
            calculations (e.g. "America/Los_Angeles").
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.calendar_id = calendar_id
        self.timezone = timezone
        self.service = self._authenticate()

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    def _authenticate(self):
        creds = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"OAuth credentials file not found at "
                        f"'{self.credentials_path}'. Download it from the "
                        f"Google Cloud Console (APIs & Services > Credentials)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        return build("calendar", "v3", credentials=creds)

    # ------------------------------------------------------------------ #
    # Public methods
    # ------------------------------------------------------------------ #

    def list_events(
        self,
        time_min: str,
        time_max: str,
        max_results: int = 50,
    ) -> List[dict]:
        """
        Return upcoming schedule items between `time_min` and `time_max`.

        Parameters accept ISO 8601 strings or natural-language expressions
        (e.g. "today", "next Monday").

        Returns
        -------
        A list of dicts, each containing: id, summary, start, end,
        description, location, and htmlLink.
        """
        time_min_iso = to_iso8601(time_min)
        time_max_iso = to_iso8601(time_max)

        try:
            response = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=self._ensure_z_suffix(time_min_iso),
                    timeMax=self._ensure_z_suffix(time_max_iso),
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(f"Failed to list events: {error}") from error

        events = response.get("items", [])
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "(no title)"),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                "description": e.get("description", ""),
                "location": e.get("location", ""),
                "htmlLink": e.get("htmlLink", ""),
            }
            for e in events
        ]

    def add_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict:
        """
        Create a new calendar event.

        `start` and `end` accept ISO 8601 strings or natural-language
        expressions (e.g. "next Thursday afternoon").

        Returns
        -------
        The created event resource as returned by the Calendar API,
        including its `id` and `htmlLink`.
        """
        start_iso = to_iso8601(start)
        end_iso = to_iso8601(end)

        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": self.timezone},
            "end": {"dateTime": end_iso, "timeZone": self.timezone},
        }
        if location:
            event_body["location"] = location

        try:
            created = (
                self.service.events()
                .insert(calendarId=self.calendar_id, body=event_body)
                .execute()
            )
        except HttpError as error:
            raise RuntimeError(f"Failed to create event: {error}") from error

        return created

    def check_conflicts(self, start: str, end: str) -> List[dict]:
        """
        Check whether the given window overlaps any existing events.

        Returns
        -------
        A list of conflicting events (empty list means no conflicts).
        Truthiness of the return value can be used as a boolean check,
        e.g.:
            if cal.check_conflicts(start, end):
                ...
        """
        start_iso = to_iso8601(start)
        end_iso = to_iso8601(end)
        start_dt = dt.datetime.fromisoformat(start_iso)
        end_dt = dt.datetime.fromisoformat(end_iso)

        candidates = self.list_events(start_iso, end_iso)

        conflicts = []
        for event in candidates:
            try:
                ev_start = dt.datetime.fromisoformat(event["start"])
                ev_end = dt.datetime.fromisoformat(event["end"])
            except (ValueError, TypeError):
                # All-day events use date-only strings; treat as full-day.
                continue

            if ev_start < end_dt and ev_end > start_dt:
                conflicts.append(event)

        return conflicts

    def get_free_slots(
        self,
        start_time: str,
        end_time: str,
        duration_minutes: int = 30,
        working_hours: Optional[Tuple[int, int]] = None,
    ) -> List[dict]:
        """
        Scan the window between `start_time` and `end_time` for available
        blocks of at least `duration_minutes`.

        Parameters
        ----------
        start_time, end_time:
            ISO 8601 strings or natural-language expressions bounding the
            scan window.
        duration_minutes:
            Minimum length (in minutes) a gap must have to count as free.
        working_hours:
            Optional (start_hour, end_hour) tuple, e.g. (9, 17), to
            restrict free slots to a daily working window.

        Returns
        -------
        A list of dicts: [{"start": iso_str, "end": iso_str}, ...]
        """
        start_iso = to_iso8601(start_time)
        end_iso = to_iso8601(end_time)
        window_start = dt.datetime.fromisoformat(start_iso)
        window_end = dt.datetime.fromisoformat(end_iso)

        busy_events = self.list_events(start_iso, end_iso, max_results=250)

        busy_periods = []
        for event in busy_events:
            try:
                ev_start = dt.datetime.fromisoformat(event["start"])
                ev_end = dt.datetime.fromisoformat(event["end"])
            except (ValueError, TypeError):
                continue
            ev_start = max(ev_start, window_start)
            ev_end = min(ev_end, window_end)
            if ev_start < ev_end:
                busy_periods.append((ev_start, ev_end))

        busy_periods.sort(key=lambda p: p[0])

        # Merge overlapping/adjacent busy periods.
        merged: List[Tuple[dt.datetime, dt.datetime]] = []
        for period_start, period_end in busy_periods:
            if merged and period_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], period_end))
            else:
                merged.append((period_start, period_end))

        # Walk the gaps between busy periods.
        free_slots = []
        cursor = window_start
        min_gap = dt.timedelta(minutes=duration_minutes)

        for busy_start, busy_end in merged:
            if busy_start > cursor:
                free_slots.extend(
                    self._split_by_working_hours(cursor, busy_start, min_gap, working_hours)
                )
            cursor = max(cursor, busy_end)

        if cursor < window_end:
            free_slots.extend(
                self._split_by_working_hours(cursor, window_end, min_gap, working_hours)
            )

        return [
            {"start": slot_start.isoformat(), "end": slot_end.isoformat()}
            for slot_start, slot_end in free_slots
        ]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_by_working_hours(
        gap_start: dt.datetime,
        gap_end: dt.datetime,
        min_gap: dt.timedelta,
        working_hours: Optional[Tuple[int, int]],
    ) -> List[Tuple[dt.datetime, dt.datetime]]:
        """Clip a free gap to working hours (if given) and filter by min length."""
        if gap_end - gap_start < min_gap and working_hours is None:
            return []

        if working_hours is None:
            return [(gap_start, gap_end)] if gap_end - gap_start >= min_gap else []

        wh_start, wh_end = working_hours
        slots = []
        day_cursor = gap_start

        while day_cursor.date() <= gap_end.date():
            day_wh_start = day_cursor.replace(hour=wh_start, minute=0, second=0, microsecond=0)
            day_wh_end = day_cursor.replace(hour=wh_end, minute=0, second=0, microsecond=0)

            slot_start = max(gap_start, day_wh_start, day_cursor)
            slot_end = min(gap_end, day_wh_end)

            if slot_end - slot_start >= min_gap:
                slots.append((slot_start, slot_end))

            day_cursor = (day_cursor + dt.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        return slots

    @staticmethod
    def _ensure_z_suffix(iso_string: str) -> str:
        """Ensure a timezone-naive ISO string carries a 'Z' or offset for the API."""
        if re.search(r"(Z|[+-]\d{2}:\d{2})$", iso_string):
            return iso_string
        return iso_string + "Z"


if __name__ == "__main__":
    # Simple manual smoke test / usage example.
    cal = CalendarTools()

    start_str, end_str = parse_natural_datetime("next Thursday afternoon")
    print(f"Parsed window: {start_str} -> {end_str}")

    print("Free slots:")
    for slot in cal.get_free_slots(start_str, end_str):
        print(f"  {slot['start']} -> {slot['end']}")

    print("Upcoming events this week:")
    for event in cal.list_events("today", "in 7 days"):
        print(f"  {event['summary']}: {event['start']} -> {event['end']}")