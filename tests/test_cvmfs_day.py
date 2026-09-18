# SPDX-License-Identifier: GPL-3.0-or-later
"""{day} nightly path slot: resolve_day (override/system/auto-weekday) and
bake_day (substitute/collapse/no-op). Layout-only — never hashed or stored."""
from datetime import datetime, timezone
from bits_helpers.cvmfs_layout import resolve_day, bake_day, bake_release

FRI = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)   # a Friday
MON = datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc)   # a Monday


def test_auto_weekday_utc_fixed_table():
    assert resolve_day({}, now=FRI) == "Fri"
    assert resolve_day({}, now=MON) == "Mon"


def test_override_wins_verbatim():
    assert resolve_day({}, override="Wed", now=FRI) == "Wed"
    assert resolve_day({}, override="  Thu  ", now=FRI) == "Thu"
    # explicit empty override => collapse (empty string, not the auto weekday)
    assert resolve_day({}, override="", now=FRI) == ""


def test_system_day_then_toplevel_then_auto():
    assert resolve_day({"system": {"day": "Sat"}}, now=FRI) == "Sat"
    assert resolve_day({"day": "Sun"}, now=FRI) == "Sun"
    assert resolve_day({}, now=FRI) == "Fri"
    # CLI override beats a system: day
    assert resolve_day({"system": {"day": "Sat"}}, override="Tue", now=FRI) == "Tue"


def test_bake_day_substitute_and_collapse():
    t = "{prefix}/nightlies/{release}/{day}/{pkg}/{version}/{platform}"
    assert bake_day(t, "Fri") == \
        "{prefix}/nightlies/{release}/Fri/{pkg}/{version}/{platform}"
    # empty collapses the whole {day}/ segment, no double slash
    assert bake_day(t, "") == \
        "{prefix}/nightlies/{release}/{pkg}/{version}/{platform}"


def test_bake_day_noop_on_templates_without_day():
    t = "{prefix}/{platform}/Packages/{pkg}/{tag}"
    assert bake_day(t, "Fri") == t
    assert bake_day(t, "") == t


def test_release_then_day_renders_lcg_nightly_path():
    t = "{prefix}/nightlies/{release}/{day}/{pkg}/{version}/{platform}"
    out = bake_day(bake_release(t, "dev4"), resolve_day({}, now=FRI))
    assert out == "{prefix}/nightlies/dev4/Fri/{pkg}/{version}/{platform}"


def test_present_null_day_collapses_both_placements():
    # key present with null/empty => collapse ("" ), NOT auto — aligned for
    # system: day and top-level day.
    from datetime import datetime, timezone
    fri = datetime(2026, 9, 18, tzinfo=timezone.utc)
    assert resolve_day({"system": {"day": None}}, now=fri) == ""
    assert resolve_day({"day": None}, now=fri) == ""
    assert resolve_day({"system": {"day": ""}}, now=fri) == ""
    # absent => auto
    assert resolve_day({"system": {}}, now=fri) == "Fri"
