import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import caldav
from icalendar import Calendar as iCal
from icalendar import Calendar, Event

logger = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"

# Wall-clock timezone for naive datetime inputs on the write path.
# iCloud stores/returns event times in UTC, but callers (e.g. the morning
# briefing routine) pass local wall-clock times. Configurable via env.
LOCAL_TZ = ZoneInfo(os.getenv("CALENDAR_TZ", "Europe/Berlin"))


def _to_utc(value: str) -> datetime:
    """Parse an ISO datetime string and return it as a UTC-aware datetime.

    A naive string (no offset, e.g. ``2026-06-17T14:15:00``) is interpreted as
    local wall-clock time in ``LOCAL_TZ`` and converted to UTC — handling the
    CEST/CET (and any DST) offset automatically. A timezone-aware string is
    honoured and converted to UTC. Storing UTC keeps the read path (which
    returns UTC) and the write path symmetric.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def _make_client(username: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=username, password=password)


def _parse_dt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _event_to_dict(event) -> dict:
    """Parse a caldav Event into a plain dict using the icalendar library."""
    try:
        cal = iCal.from_ical(event.data)
        for comp in cal.walk("VEVENT"):
            dtstart = comp.get("DTSTART")
            dtend   = comp.get("DTEND")
            return {
                "uid":         str(comp.get("UID", "")),
                "title":       str(comp.get("SUMMARY", "")),
                "start":       _parse_dt(dtstart.dt if dtstart else None),
                "end":         _parse_dt(dtend.dt if dtend else None),
                "description": str(comp.get("DESCRIPTION", "")),
                "location":    str(comp.get("LOCATION", "")),
            }
    except Exception as exc:
        logger.warning("Could not parse event: %s", exc)
    return {}


def _build_ical(title: str, start: datetime, end: datetime,
                description: str, location: str, uid: str | None = None) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//icloud-calendar-mcp//EN")
    cal.add("version", "2.0")

    event = Event()
    event.add("uid", uid or str(uuid.uuid4()))
    event.add("summary", title)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.now(timezone.utc))
    if description:
        event.add("description", description)
    if location:
        event.add("location", location)

    cal.add_component(event)
    return cal.to_ical()


def _parse_date_range(start_date: str, end_date: str) -> tuple:
    """
    Convert ISO date strings to UTC datetimes for CalDAV date_search.
    When end_date is a date-only string (no 'T'), extend by one day so the
    range is [start 00:00Z, end+1 00:00Z) and covers the full end calendar day
    regardless of the event's stored timezone offset.
    """
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_naive = datetime.fromisoformat(end_date)
    if "T" not in end_date:
        end_naive += timedelta(days=1)
    end = end_naive.replace(tzinfo=timezone.utc)
    return start, end


def _find_calendar(all_calendars: list, name: str) -> tuple:
    """
    Return (calendar, error_string). Tries exact match then case-insensitive.
    On failure, returns (None, message listing available names).
    """
    by_name = {str(c.name): c for c in all_calendars}

    if name in by_name:
        return by_name[name], None

    name_lower = name.lower()
    for cal_name, cal in by_name.items():
        if cal_name.lower() == name_lower:
            return cal, None

    available = list(by_name.keys())
    return None, f"Calendar '{name}' not found. Available calendars: {available}"


def register_tools(mcp, username: str, password: str) -> None:

    @mcp.tool()
    def list_calendars() -> list[dict]:
        """List all calendars in the iCloud account."""
        client = _make_client(username, password)
        principal = client.principal()
        return [
            {"name": str(c.name), "url": str(c.url)}
            for c in principal.calendars()
        ]

    @mcp.tool()
    def list_events(calendar_name: str, start_date: str, end_date: str) -> list[dict]:
        """
        List events in a calendar within a date range.

        Args:
            calendar_name: Calendar name (from list_calendars). Case-insensitive.
            start_date:    ISO date string, e.g. '2026-05-01'.
            end_date:      ISO date string, e.g. '2026-05-31'.
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return [{"error": err}]

        start, end = _parse_date_range(start_date, end_date)
        # expand=False: iCloud CalDAV does not support server-side expansion
        events = cal.date_search(start=start, end=end, expand=False)
        return [d for d in (_event_to_dict(e) for e in events) if d]

    @mcp.tool()
    def get_event(calendar_name: str, event_uid: str) -> dict:
        """
        Get a single event by UID.

        Args:
            calendar_name: Calendar name (from list_calendars). Case-insensitive.
            event_uid:     UID string from list_events or search_events.
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return {"error": err}
        try:
            event = cal.event_by_uid(event_uid)
            return _event_to_dict(event)
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def create_event(
        calendar_name: str,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict:
        """
        Create a new calendar event.

        Args:
            calendar_name: Calendar name (from list_calendars). Case-insensitive.
            title:         Event title/summary.
            start:         ISO datetime string, e.g. '2026-05-20T10:00:00'. A
                           naive value (no offset) is treated as local wall-clock
                           time (CALENDAR_TZ, default Europe/Berlin); an explicit
                           offset is honoured. Stored as UTC either way.
            end:           ISO datetime string, same timezone rules as start.
            description:   Optional event description.
            location:      Optional location string.
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return {"error": err}

        uid      = str(uuid.uuid4())
        start_dt = _to_utc(start)
        end_dt   = _to_utc(end)
        ical_data = _build_ical(title, start_dt, end_dt, description, location, uid)

        try:
            cal.save_event(ical_data)
            return {"status": "created", "uid": uid}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def update_event(
        calendar_name: str,
        event_uid: str,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict:
        """
        Update an existing calendar event. Only provided fields are changed.

        Args:
            calendar_name: Calendar name (from list_calendars). Case-insensitive.
            event_uid:     UID of the event to update.
            title:         New title (optional).
            start:         New start ISO datetime (optional). Naive values are
                           treated as local wall-clock time (CALENDAR_TZ, default
                           Europe/Berlin) and stored as UTC; see create_event.
            end:           New end ISO datetime (optional). Same rules as start.
            description:   New description (optional).
            location:      New location (optional).
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return {"error": err}

        try:
            event = cal.event_by_uid(event_uid)
        except Exception as exc:
            return {"error": str(exc)}

        vevent = event.instance.vevent
        if title is not None:
            vevent.summary.value = title
        if start is not None:
            vevent.dtstart.value = _to_utc(start)
        if end is not None:
            vevent.dtend.value = _to_utc(end)
        if description is not None:
            if hasattr(vevent, "description"):
                vevent.description.value = description
            else:
                vevent.add("description").value = description
        if location is not None:
            if hasattr(vevent, "location"):
                vevent.location.value = location
            else:
                vevent.add("location").value = location

        try:
            event.save()
            return {"status": "updated", "uid": event_uid}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def delete_event(calendar_name: str, event_uid: str) -> dict:
        """
        Delete a calendar event by UID.

        Args:
            calendar_name: Calendar name (from list_calendars). Case-insensitive.
            event_uid:     UID of the event to delete.
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return {"error": err}

        try:
            event = cal.event_by_uid(event_uid)
            event.delete()
            return {"status": "deleted", "uid": event_uid}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def search_events(query: str, start_date: str, end_date: str) -> list[dict]:
        """
        Search for events matching a text query across all calendars.

        Args:
            query:      Text to search for in title, description, or location.
            start_date: ISO date string, e.g. '2026-05-01'.
            end_date:   ISO date string, e.g. '2026-05-31'.
        """
        client = _make_client(username, password)
        principal = client.principal()
        start, end = _parse_date_range(start_date, end_date)
        q          = query.lower()
        results = []

        for cal in principal.calendars():
            try:
                # expand=False: iCloud CalDAV does not support server-side expansion
                events = cal.date_search(start=start, end=end, expand=False)
                for e in events:
                    d = _event_to_dict(e)
                    if not d:
                        continue
                    if (q in d["title"].lower()
                            or q in d["description"].lower()
                            or q in d["location"].lower()):
                        d["calendar"] = str(cal.name)
                        results.append(d)
            except Exception as exc:
                logger.warning("Error searching calendar '%s': %s", cal.name, exc)

        return results
