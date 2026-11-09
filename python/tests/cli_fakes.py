"""Fake clients, feeds and recording consoles for the CLI tests."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from rich.console import Console

from vayuayan.cli_readings import IST
from vayuayan.exceptions import DataNotFoundError, NetworkError

NOW = datetime(2026, 11, 9, 11, 0, tzinfo=IST)
FRESH = "09-11-2026 10:00:00"
OLD = "09-11-2026 00:00:00"


def pollutant(name, avg, low=None, high=None, hourly=None):
    return {
        "indexId": name,
        "avg": str(avg),
        "min": str(low if low is not None else avg),
        "max": str(high if high is not None else avg),
        "Hourly_sub_index": str(hourly if hourly is not None else avg),
    }


def feed_station(sid, name, lat, lon, aqi="82", updated=FRESH, pollutants=None):
    return {
        "id": sid,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "live": bool(updated),
        "lastUpdate": updated,
        "airQualityIndex": {"value": aqi},
        "pollutants": (
            pollutants
            if pollutants is not None
            else [pollutant("PM10", 82, 44, 278, 278), pollutant("OZONE", 20)]
        ),
    }


def feed():
    """The feed in the package's shape: two cities, one with an offline station."""
    return [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [
                feed_station("site_1", "Powai, Mumbai - MPCB", 19.13, 72.91),
                feed_station("site_2", "Kurla, Mumbai - MPCB", 19.08, 72.88, aqi="310"),
                feed_station(
                    "site_3",
                    "Colaba, Mumbai - IITM",
                    18.91,
                    72.82,
                    aqi="NA",
                    updated="NA",
                    pollutants=[],
                ),
            ],
        },
        {
            "cityName": "Delhi",
            "stateID": "Delhi",
            "stationsInCity": [
                feed_station("site_9", "ITO, Delhi - CPCB", 28.62, 77.24, aqi="401")
            ],
        },
    ]


def catalogue():
    """The rows of station_table for the feed, plus one station it lacks."""
    return pd.DataFrame(
        [
            ("site_9", "ITO, Delhi - CPCB", "Delhi", "Delhi", 28.62, 77.24),
            ("site_3", "Colaba, Mumbai - IITM", "Mumbai", "Maharashtra", 18.91, 72.82),
            ("site_2", "Kurla, Mumbai - MPCB", "Mumbai", "Maharashtra", 19.08, 72.88),
            ("site_1", "Powai, Mumbai - MPCB", "Mumbai", "Maharashtra", 19.13, 72.91),
            ("site_8", "Anand Vihar, Delhi - DPCC", "Delhi", "Delhi", 28.65, 77.32),
            ("site_7", "Anand Vihar, Hapur - UPPCB", "Hapur", "UP", 28.73, 77.75),
            ("site_6", "Solo Park, Panaji - GSPCB", "Panaji", "Goa", None, None),
        ],
        columns=[
            "station_id",
            "station_name",
            "city",
            "state",
            "latitude",
            "longitude",
        ],
    )


def workbook(months=None):
    """A daily workbook with a footer row, as CPCB publishes it."""
    data = {"Day": list(range(1, 32)) + ["Minimum"]}
    for name, values in (months or {"January": {1: 40, 2: 150, 3: 420}}).items():
        data[name] = [values.get(day) for day in range(1, 32)] + [1]
    return pd.DataFrame(data)


def computed_days():
    """What daily_aqi returns for a few days."""
    return pd.DataFrame(
        {
            "date": [
                datetime(2025, 1, 1).date(),
                datetime(2025, 1, 2).date(),
                datetime(2025, 1, 3).date(),
            ],
            "aqi": [150.0, float("nan"), 310.0],
            "category": ["x", "x", "x"],
            "dominant_pollutant": ["PM2.5", None, "PM10"],
        }
    )


def report_table():
    """A report export of two hours."""
    return pd.DataFrame(
        {
            "Timestamp": pd.to_datetime(["2026-11-08 00:00", "2026-11-08 01:00"]),
            "PM2.5 (µg/m³)": [10.0, 20.0],
            "CO (mg/m³)": [float("nan"), float("nan")],
        }
    )


class FakeLive:
    """Stands in for CPCBLive."""

    def __init__(self, cities=None, location=(19.1, 72.9), down=False, ip_down=False):
        self.cities = feed() if cities is None else cities
        self.location = location
        self.down = down
        self.ip_down = ip_down

    def get_all_india(self):
        if self.down:
            raise NetworkError("No CPCB station list is available")
        return self.cities

    def get_system_location(self):
        if self.ip_down:
            raise NetworkError("Geolocation lookup failed")
        return self.location


class FakeHistorical:
    """Stands in for CPCBHistorical."""

    def __init__(self, table=None, sheet=None, no_data=False):
        self.table = catalogue() if table is None else table
        self.sheet = workbook() if sheet is None else sheet
        self.no_data = no_data
        self.calls = []

    def station_table(self, state="", city=""):
        self.calls.append(("station_table", state, city))
        table = self.table
        if city:
            table = table[table["city"].str.lower() == city.lower()]
        if state:
            table = table[table["state"].str.lower() == state.lower()]
        return table.reset_index(drop=True)

    def _sheet(self, kind, *args, **kwargs):
        self.calls.append((kind, args, kwargs))
        if self.no_data:
            raise DataNotFoundError("Data not found")
        return self.sheet

    def download_past_year_aqi_data_station_level(self, *args, **kwargs):
        return self._sheet("station_year", *args, **kwargs)

    def download_past_year_aqi_data_city_level(self, *args, **kwargs):
        return self._sheet("city_year", *args, **kwargs)

    def daily_aqi(self, *args, **kwargs):
        self.calls.append(("daily_aqi", args, kwargs))
        return computed_days()

    def download_station_report(self, *args, **kwargs):
        self.calls.append(("station_report", args, kwargs))
        return report_table()

    def download_city_report(self, *args, **kwargs):
        self.calls.append(("city_report", args, kwargs))
        return report_table()


def recording(width=80, terminal=True):
    """A console that records what it prints at a fixed width."""
    return Console(
        file=io.StringIO(),
        record=True,
        width=width,
        force_terminal=terminal,
        color_system="truecolor" if terminal else None,
        highlight=False,
        legacy_windows=False,
    )


def written_to(console):
    """The characters a console sent to its file, with any colour codes."""
    return console.file.getvalue()


def text_of(console):
    """What a recording console has printed, as plain text."""
    return console.export_text(clear=False)


def svg_of(console):
    """What a recording console has printed, as SVG with its exact colours."""
    return console.export_svg(clear=False).lower()
