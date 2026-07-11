"""Timezone handling for event writes.

Regression guard for two bugs:
1. The +2h calendar bug: the routine passes local wall-clock times (e.g.
   "14:15" in Berlin) to create_event/update_event. These must be interpreted
   as local time, not stamped as UTC verbatim (which shifted every event
   forward by the CEST/CET offset).
2. The "GMT" edit bug: events were stored as a bare UTC ``Z`` timestamp with
   no ``TZID``. Apple Calendar displayed the converted local time correctly,
   but tagged the event's own timezone as GMT, so manually nudging the time
   in the edit view silently edited in GMT instead of Europe/Berlin. Storing
   with an explicit ``TZID=Europe/Berlin`` (see ``_build_ical``) fixes this.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import caldav
from icalendar import vDDDTypes

from icloud_calendar_mcp.calendar import _build_ical, _to_local

BERLIN = ZoneInfo("Europe/Berlin")


def test_naive_input_is_local_summer():
    # 14:15 in June is CEST (UTC+2).
    result = _to_local("2026-06-17T14:15:00")
    assert result == datetime(2026, 6, 17, 14, 15, tzinfo=BERLIN)
    assert result.utcoffset().total_seconds() == 2 * 3600


def test_naive_input_is_local_winter():
    # 14:15 in January is CET (UTC+1).
    result = _to_local("2026-01-15T14:15:00")
    assert result == datetime(2026, 1, 15, 14, 15, tzinfo=BERLIN)
    assert result.utcoffset().total_seconds() == 1 * 3600


def test_aware_input_is_converted_to_local():
    # An explicit offset is honoured, then normalized to Berlin wall-clock time.
    result = _to_local("2026-06-17T08:15:00-04:00")
    assert result == datetime(2026, 6, 17, 14, 15, tzinfo=BERLIN)


def test_result_is_berlin_aware():
    assert _to_local("2026-06-17T14:15:00").tzinfo == BERLIN


def test_build_ical_uses_tzid_not_utc_z():
    start = _to_local("2026-06-17T14:15:00")
    end = _to_local("2026-06-17T15:15:00")
    ics = _build_ical("Test", start, end, "", "").decode()

    assert "DTSTART;TZID=Europe/Berlin:20260617T141500" in ics
    assert "DTEND;TZID=Europe/Berlin:20260617T151500" in ics
    # The bug this guards against: a bare Z/UTC stamp with no named zone.
    assert "DTSTART:20260617T121500Z" not in ics
    assert "BEGIN:VTIMEZONE" in ics
    assert "TZID:Europe/Berlin" in ics


def test_update_event_mutation_keeps_tzid():
    # Mirrors update_event's edit_icalendar_instance block against an event
    # produced by create_event, without touching the network. Also guards
    # against the (unrelated) update_event crash: caldav >= 2.0 no longer
    # bundles vobject, so the old `event.instance.vevent` accessor returned
    # None and raised AttributeError before this rewrite.
    ics = _build_ical(
        "Original", _to_local("2026-06-17T14:15:00"), _to_local("2026-06-17T15:15:00"),
        "desc", "loc", uid="test-uid",
    )
    event = caldav.Event(data=ics)

    with event.edit_icalendar_instance() as ical:
        vevent = next(c for c in ical.subcomponents if c.name == "VEVENT")
        vevent["SUMMARY"] = "Updated"
        vevent["DTSTART"] = vDDDTypes(_to_local("2026-06-17T16:00:00"))
        ical.add_missing_timezones()

    assert "SUMMARY:Updated" in event.data
    assert "DTSTART;TZID=Europe/Berlin:20260617T160000" in event.data
    # End time, description, and location were left untouched.
    assert "DTEND;TZID=Europe/Berlin:20260617T151500" in event.data
    assert "DESCRIPTION:desc" in event.data
    assert "LOCATION:loc" in event.data
