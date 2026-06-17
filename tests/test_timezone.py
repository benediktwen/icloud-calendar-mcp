"""Timezone handling for event writes.

Regression guard for the +2h calendar bug: the routine passes local wall-clock
times (e.g. "14:15" in Munich) to create_event/update_event. These must be
interpreted as local time and stored as UTC — not stamped as UTC verbatim,
which shifted every event forward by the CEST/CET offset.
"""

from datetime import datetime, timezone

from icloud_calendar_mcp.calendar import _to_utc


def test_naive_input_is_local_summer_then_utc():
    # 14:15 Europe/Berlin in June is CEST (UTC+2) -> 12:15 UTC
    assert _to_utc("2026-06-17T14:15:00") == datetime(2026, 6, 17, 12, 15, tzinfo=timezone.utc)


def test_naive_input_is_local_winter_then_utc():
    # 14:15 Europe/Berlin in January is CET (UTC+1) -> 13:15 UTC
    assert _to_utc("2026-01-15T14:15:00") == datetime(2026, 1, 15, 13, 15, tzinfo=timezone.utc)


def test_aware_input_is_converted_to_utc():
    # An explicit offset is honoured, not overwritten.
    assert _to_utc("2026-06-17T14:15:00+02:00") == datetime(2026, 6, 17, 12, 15, tzinfo=timezone.utc)


def test_result_is_utc_aware():
    assert _to_utc("2026-06-17T14:15:00").tzinfo == timezone.utc
