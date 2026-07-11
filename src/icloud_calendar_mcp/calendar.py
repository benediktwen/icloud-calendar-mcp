import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import caldav
from icalendar import Calendar as iCal
from icalendar import Calendar, Event, vDDDTypes

logger = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"

# Wall-clock timezone for naive datetime inputs, and the zone events are
# written in (with an explicit TZID, see _build_ical). Configurable via env.
LOCAL_TZ = ZoneInfo(os.getenv("CALENDAR_TZ", "Europe/Berlin"))


def _to_local(value: str) -> datetime:
    """Parse an ISO datetime string and return it as a LOCAL_TZ-aware datetime.

    A naive string (no offset, e.g. ``2026-06-17T14:15:00``) is interpreted as
    local wall-clock time in ``LOCAL_TZ``. A timezone-aware string is honoured
    and converted to ``LOCAL_TZ``. Events are written with an explicit
    ``TZID=<LOCAL_TZ>`` (see ``_build_ical``), so calendar apps show and edit
    the event in that named zone instead of GMT/UTC.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _make_client(username: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=username, password=password)


def _event_by_uid(client: caldav.DAVClient, cal, event_uid: str):
    """Fetch a calendar object by UID, resilient to iCloud CalDAV.

    caldav's ``Calendar.event_by_uid`` issues a calendar-query REPORT that
    iCloud frequently rejects with ``412 Precondition Failed``. Since caldav
    saves objects at ``<calendar_url>/<uid>.ics``, on failure we address the
    object directly (a plain GET), which iCloud serves without complaint.
    """
    try:
        return cal.event_by_uid(event_uid)
    except Exception:
        url = cal.url.join(quote(event_uid) + ".ics")
        event = caldav.Event(client=client, url=url, parent=cal)
        event.load()
        return event


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
    cal.add_missing_timezones()
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
            event = _event_by_uid(client, cal, event_uid)
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
                           offset is honoured. Stored with an explicit
                           TZID=<CALENDAR_TZ> either way, so calendar apps show
                           and edit the event in that zone, not GMT/UTC.
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
        start_dt = _to_local(start)
        end_dt   = _to_local(end)
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
                           Europe/Berlin); see create_event for how it's stored.
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
            event = _event_by_uid(client, cal, event_uid)
        except Exception as exc:
            return {"error": str(exc)}

        try:
            with event.edit_icalendar_instance() as ical:
                vevent = next(c for c in ical.subcomponents if c.name == "VEVENT")
                if title is not None:
                    vevent["SUMMARY"] = title
                if start is not None:
                    vevent["DTSTART"] = vDDDTypes(_to_local(start))
                if end is not None:
                    vevent["DTEND"] = vDDDTypes(_to_local(end))
                if description is not None:
                    vevent["DESCRIPTION"] = description
                if location is not None:
                    vevent["LOCATION"] = location
                ical.add_missing_timezones()
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
            event = _event_by_uid(client, cal, event_uid)
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
