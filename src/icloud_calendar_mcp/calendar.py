import logging
import uuid
from datetime import date, datetime, timezone

import caldav
from icalendar import Calendar as iCal
from icalendar import Calendar, Event

logger = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"


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

        start  = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end    = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
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
            start:         ISO datetime string, e.g. '2026-05-20T10:00:00'.
            end:           ISO datetime string, e.g. '2026-05-20T11:00:00'.
            description:   Optional event description.
            location:      Optional location string.
        """
        client = _make_client(username, password)
        principal = client.principal()
        cal, err = _find_calendar(principal.calendars(), calendar_name)
        if err:
            return {"error": err}

        uid      = str(uuid.uuid4())
        start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt   = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
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
            start:         New start ISO datetime (optional).
            end:           New end ISO datetime (optional).
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
            vevent.dtstart.value = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        if end is not None:
            vevent.dtend.value = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
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
        start   = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end     = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        q       = query.lower()
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
