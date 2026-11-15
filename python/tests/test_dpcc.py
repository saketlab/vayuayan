"""DPCC hourly pages: parsing, request windows, caching and the tidy table (offline)."""

import datetime as dt
from types import SimpleNamespace

import pytest

from vayuayan import dpcc
from vayuayan.tidy import TIDY_COLUMNS


def page(hours, values):
    """A DPCC Advance Search result with its Highcharts arrays, as the site writes them."""
    cats = ",".join(f"'{h}'" for h in hours)
    return (
        "<html>Search Result of Particulate Matter < 2.5 <script>xAxis: {categories: ["
        + cats
        + "],}, series: [{ /*name: 'Tokyo', data: [7.0, 6.9]}, {*/ name: 'PM', data: ["
        + ",".join(values)
        + "] }]</script></html>"
    )


def test_parse_reads_the_live_series_and_skips_empty_hours():
    got = dpcc.parse_dpcc_page(
        page(
            ["2026-11-09 01:00:00", "2026-11-09 02:00:00", "2026-11-09 03:00:00"],
            ["3124.0", "null", "2690.0"],
        )
    )
    assert got == [("2026-11-09 01:00:00", 3124.0), ("2026-11-09 03:00:00", 2690.0)]
    assert dpcc.parse_dpcc_page("<html>Search Result of x</html>") == []
    with pytest.raises(ValueError, match="changed"):
        dpcc.parse_dpcc_page("<html>Advance Search form only</html>")


def test_windows_are_at_most_six_days_and_join_up():
    w = dpcc._windows(dt.date(2026, 11, 1), dt.date(2026, 11, 10))
    assert w[0][0] == dt.datetime(
        2026, 10, 31, 23
    )  # the site returns the hours after the start
    assert w[-1][1] == dt.datetime(2026, 11, 10, 23)
    assert all(b - a <= dt.timedelta(days=6) for a, b in w)
    assert all(w[i][1] == w[i + 1][0] for i in range(len(w) - 1))


def test_dpcc_hourly_is_tidy_and_keeps_only_the_days_asked(monkeypatch):
    seen = []

    def fake(code, par, pg, w0, w1):
        seen.append((code, par, pg))
        return page(
            ["2026-11-08 23:00:00", "2026-11-09 02:00:00", "2026-11-10 00:00:00"],
            ["1636", "3744", "400"],
        )

    monkeypatch.setattr(dpcc, "_fetch", fake)
    got = dpcc.dpcc_hourly("mundka", "2026-11-09", parameters=["PM2.5", "O3"])
    assert list(got.columns) == TIDY_COLUMNS
    assert seen == [
        ("Mundka", "PM25", "AallAdvanceSearchMet"),
        ("Mundka", "O3", "AallAdvanceSearchCconc"),
    ]
    pm = got[got.pollutant == "PM2.5"]
    assert (
        pm.value.tolist() == [3744.0]
        and str(pm.timestamp.iloc[0]) == "2026-11-09 02:00:00"
    )
    assert set(got.pollutant) == {"PM2.5", "Ozone"} and set(got.city) == {"Delhi"}


def test_bad_arguments_are_errors():
    with pytest.raises(ValueError, match="2025-01-01"):
        dpcc.dpcc_hourly("Mundka", "2024-12-31")
    with pytest.raises(ValueError, match="unknown DPCC station"):
        dpcc.dpcc_hourly("Gurugram", "2026-11-09")
    with pytest.raises(ValueError, match="unknown DPCC parameter"):
        dpcc.dpcc_hourly("JNU", "2026-11-09", parameters="PM1")
    with pytest.raises(ValueError, match="before start"):
        dpcc.dpcc_hourly("JNU", "2026-11-09", "2026-11-01")
    assert len(dpcc.dpcc_stations()) == 31


def test_old_windows_are_cached_and_recent_ones_are_not(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append((url, kw["data"]["fDate"]))
        return SimpleNamespace(text=page(["2025-01-01 00:00:00"], ["90"]))

    monkeypatch.setattr(dpcc.http_client, "request", fake)
    monkeypatch.setattr(dpcc.time, "sleep", lambda s: None)
    old = (dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 2))
    for _ in range(2):
        dpcc._fetch("Jnu", "PM25", "AallAdvanceSearchMet", *old)
    assert len(calls) == 1
    assert calls[0] == (
        "https://www.dpccairdata.com/dpccairdata/display/AallAdvanceSearchMet.php?stName=Sm51",
        "2025-01-01 00:00",
    )
    now = dt.datetime.now()
    for _ in range(2):
        dpcc._fetch(
            "Jnu", "PM25", "AallAdvanceSearchMet", now - dt.timedelta(hours=5), now
        )
    assert len(calls) == 3
