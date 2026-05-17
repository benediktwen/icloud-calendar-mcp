import logging
import uuid
from datetime import date, datetime, timezone, timedelta

import caldav
from icalendar import Calendar, Event, vText

logger = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"


def _make_client(username: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=username, password=password)


def _parse_dt(value) -> str:
    """Return an ISO-8601 string from a caldav dt property value."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _event_to_dict(vevent) -> dict:
    comp = vevent.instance.vevent if hasattr(vevent, "instance") else vevent
    return {
        "uid":         str(comp.get("uid", "")),
        "title":       str(comp.get("summary", "")),
        "start":       _parse_dt(getattr(comp.get("dtstart"), "dt", None)),
        "end":         _parse_dt(getattr(comp.get("dtend"), "dt", None)),
        "description": str(comp.get("description", "")),
        "location":    str(comp.get("location", "")),
    }


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
            calendar_name: Exact calendar name (from list_calendars).
            start_date: ISO date string, e.g. '2026-05-01'.
            end_date:   ISO date string, e.g. '2026-05-31'.
        """
        client = _make_client(username, password)
        principal = client.principal()
        calendars = {str(c.name): c for c in principal.calendars()}
        cal = calendars.get(calendar_name)
        if cal is None:
            return [{"error": f"Calendar '{calendar_name}' not found."}]

        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        events = cal.date_search(start=start, end=end, expand=True)
        return [_event_to_dict(e) for e in events]

    @mcp.tool()
    def get_event(calendar_name: str, event_uid: str) -> dict:
        """
        Get a single event by UID.

        Args:
            calendar_name: Exact calendar name.
            event_uid:     UID string from list_events or search_events.
        """
        client = _make_client(username, password)
        principal = client.principal()
        calendars = {str(c.name): c for c in principal.calendars()}
        cal = calendars.get(calendar_name)
        if cal is None:
            return {"error": f"Calendar '{calendar_name}' not found."}
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
            calendar_name: Exact calendar name.
            title:         Event title/summary.
            start:         ISO datetime string, e.g. '2026-05-20T10:00:00'.
            end:           ISO datetime string, e.g. '2026-05-20T11:00:00'.
            description:   Optional event description.
            location:      Optional location string.
        """
        client = _make_client(username, password)
        principal = client.principal()
        calendars = {str(c.name): c for c in principal.calendars()}
        cal = calendars.get(calendar_name)
        if cal is None:
            return {"error": f"Calendar '{calendar_name}' not found."}

        uid       = str(uuid.uuid4())
        start_dt  = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt    = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
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
            calendar_name: Exact calendar name.
            event_uid:     UID of the event to update.
            title:         New title (optional).
            start:         New start ISO datetime (optional).
            end:           New end ISO datetime (optional).
            description:   New description (optional).
            location:      New location (optional).
        """
        client = _make_client(username, password)
        principal = client.principal()
        calendars = {str(c.name): c for c in principal.calendars()}
        cal = calendars.get(calendar_name)
        if cal is None:
            return {"error": f"Calendar '{calendar_name}' not found."}

        try:
            event = cal.event_by_uid(event_uid)
        except Exception as exc:
            return {"error": str(exc)}

        vevent = event.instance.vevent
        if title is not None:
            vevent.summary.obj = title
        if start is not None:
            vevent.dtstart.value = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        if end is not None:
            vevent.dtend.value = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
        if description is not None:
            if hasattr(vevent, "description"):
                vevent.description.value = description
            else:
                vevent.add("description", description)
        if location is not None:
            if hasattr(vevent, "location"):
                vevent.location.value = location
            else:
                vevent.add("location", location)

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
            calendar_name: Exact calendar name.
            event_uid:     UID of the event to delete.
        """
        client = _make_client(username, password)
        principal = client.principal()
        calendars = {str(c.name): c for c in principal.calendars()}
        cal = calendars.get(calendar_name)
        if cal is None:
            return {"error": f"Calendar '{calendar_name}' not found."}

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
        start  = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end    = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        q      = query.lower()
        results = []

        for cal in principal.calendars():
            try:
                events = cal.date_search(start=start, end=end, expand=True)
                for e in events:
                    d = _event_to_dict(e)
                    if (q in d["title"].lower()
                            or q in d["description"].lower()
                            or q in d["location"].lower()):
                        d["calendar"] = str(cal.name)
                        results.append(d)
            except Exception as exc:
                logger.warning("Error searching calendar '%s': %s", cal.name, exc)

        return results
