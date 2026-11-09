"""What the CLI draws: content and exact colours at a fixed width."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from vayuayan import commands
from vayuayan.cli_places import catalogue_from_table, resolve_place
from vayuayan.cli_render import (
    _age,
    _clock,
    _coordinates,
    make_console,
    render,
    render_matches,
    render_problem,
)
from vayuayan.cli_render_history import heatmap, render_history, scale_legend
from vayuayan.cli_results import CommandResult
from vayuayan.cli_scale import INDIA, US
from vayuayan.commands_history import HistoryRequest
from vayuayan.commands_report import ReportRequest

from .cli_fakes import (
    NOW,
    OLD,
    FakeHistorical,
    FakeLive,
    catalogue,
    feed_station,
    recording,
    svg_of,
    text_of,
    workbook,
    written_to,
)

STATIONS = catalogue_from_table(catalogue())
TODAY = date(2026, 11, 9)


def _place(query):
    return resolve_place(query, STATIONS)


def _render(result, width=80, terminal=True, limit=None):
    out, err = recording(width, terminal), recording(width, terminal)
    render(result, out, err, limit)
    return out, err


def _live(query="powai", cities=None, **kwargs):
    return commands.live_place(FakeLive(cities, **kwargs), _place(query), NOW)


def _history(query="powai", request=None, sheet=None):
    client = FakeHistorical(sheet=sheet) if sheet is not None else FakeHistorical()
    return commands.history(
        client, _place(query), request or HistoryRequest(2025), today=TODAY
    )


def _spans_with(text, colour):
    return [s for s in text.spans if colour in str(s.style)]


def test_make_console_does_not_highlight_numbers():
    assert make_console()._highlight is False
    assert make_console(stderr=True).stderr


def test_station_panel_shows_everything_asked_for():
    out, _ = _render(_live())
    text = text_of(out)

    for expected in (
        "AQI 82",
        "Satisfactory",
        "PM10",
        "Powai, Mumbai - MPCB",
        "Mumbai, Maharashtra",
        "19.1300, 72.9100",
        "site_1",
        "9 Nov 2026, 10:00 AM IST",
        "1 hour ago",
        "Live reading",
        "Ozone",
    ):
        assert expected in text


def test_station_panel_labels_values_as_sub_indices_not_concentrations():
    out, _ = _render(_live())
    text = " ".join(text_of(out).replace("│", " ").split())

    assert "sub-indices" in text
    assert "not concentrations" in text


def test_banner_uses_the_official_colour_with_readable_text():
    out, _ = _render(_live())
    svg = svg_of(out)

    assert "#92d050" in svg
    assert "#000000" in svg


def test_old_reading_is_called_out():
    cities = [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [feed_station("site_1", "P", 1.0, 2.0, updated=OLD)],
        }
    ]
    out, _ = _render(_live(cities=cities))
    text = text_of(out)

    assert "Old reading" in text
    assert "11 hours ago" in text


def test_offline_station_is_clearly_offline():
    out, _ = _render(_live("colaba"))
    text = text_of(out)

    assert "No current reading" in text
    assert "Offline" in text
    assert "not reported" in text


def test_fetch_failure_is_not_shown_as_offline():
    out, _ = _render(_live(down=True))
    text = text_of(out)

    assert "Could not reach CPCB" in text
    assert "Offline" not in text


def test_nearest_line_says_how_it_was_located_and_has_no_ip():
    result = commands.live_near(FakeLive(location=(19.13, 72.91)), now=NOW)
    out, _ = _render(result)
    text = " ".join(text_of(out).split())

    assert "Nearest to your location: Powai, Mumbai - MPCB" in text
    assert "km away" in text
    assert "located from your IP; use `vayuayan live <place>` to choose" in text


def test_nearest_with_coordinates_does_not_mention_ip():
    result = commands.live_near(FakeLive(), (19.1, 72.9), NOW)
    out, _ = _render(result)

    assert "from the coordinates you gave" in " ".join(text_of(out).split())


def test_nearest_stale_note_is_shown():
    cities = [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [feed_station("site_1", "P", 19.1, 72.9, updated=OLD)],
        }
    ]
    out, _ = _render(commands.live_near(FakeLive(cities), now=NOW))

    assert "No station has a fresh reading" in " ".join(text_of(out).split())


def test_city_table_ranks_and_colours_each_row():
    out, _ = _render(_live("mumbai"))
    text = text_of(out)
    svg = svg_of(out)

    assert text.index("Kurla") < text.index("Powai") < text.index("Colaba")
    assert "Very Poor" in text and "offline" in text
    assert "#ff0000" in svg and "#92d050" in svg


def test_city_table_mentions_old_readings():
    cities = [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [
                feed_station("site_1", "P", 19.1, 72.9, updated=OLD),
                feed_station("site_2", "K", 19.0, 72.8),
            ],
        }
    ]
    out, _ = _render(_live("mumbai", cities=cities))

    assert "1 of these readings are old" in " ".join(text_of(out).split())


@pytest.mark.parametrize("width", [80, 120])
def test_heatmap_shows_data_gaps_and_impossible_days(width):
    result = _history()
    data = result.data
    text = heatmap(data["days"], 2025, None, INDIA, width)
    lines = text.plain.split("\n")

    assert len(lines) == 13
    assert lines[1].startswith("Jan")
    assert lines[1].split()[1:4] == ["1", "3", "6"]
    assert "·" in lines[1]
    assert len(lines[2].rstrip()) < len(lines[1].rstrip())
    assert all(len(line) <= width for line in lines)


def test_narrow_heatmap_labels_every_fifth_day_so_numbers_do_not_collide():
    header = heatmap([], 2025, None, INDIA, 80).plain.split("\n")[0].split()

    assert header == ["1", "5", "10", "15", "20", "25", "30"]


def test_wide_heatmap_labels_every_day():
    header = heatmap([], 2025, None, INDIA, 120).plain.split("\n")[0].split()

    assert header == [str(day) for day in range(1, 32)]


def test_heatmap_for_one_month_has_one_row():
    text = heatmap([], 2025, 3, INDIA, 80)

    assert len(text.plain.split("\n")) == 2
    assert "Mar" in text.plain


def test_heatmap_cells_use_the_exact_colours_of_their_scale():
    days = [{"date": "2025-01-01", "aqi": 150, "category": INDIA.category(150)}]
    india = heatmap(days, 2025, 1, INDIA, 80)
    usa = heatmap(
        [{"date": "2025-01-01", "aqi": 150, "category": US.category(150)}],
        2025,
        1,
        US,
        80,
    )

    assert _spans_with(india, "#FFFF00") and not _spans_with(india, "#FF7E00")
    assert _spans_with(usa, "#FF7E00") and not _spans_with(usa, "#FFFF00")


def test_legend_names_the_standard_and_each_category():
    india = scale_legend(INDIA).plain
    usa = scale_legend(US).plain

    assert "India National AQI (CPCB)" in india
    assert "Very Poor 301-400" in india
    assert "US AQI (EPA)" in usa
    assert "Unhealthy for Sensitive Groups 101-150" in usa
    assert "Satisfactory" not in usa and "Hazardous" not in india
    assert "no data" in usa


def test_legend_chips_stay_whole_at_width_80():
    console = recording(80)
    console.print(scale_legend(US))

    lines = text_of(console).splitlines()
    assert any("3 Unhealthy for Sensitive Groups 101-150" in line for line in lines)
    assert any("6 Hazardous 301+" in line for line in lines)


def test_history_output_prints_standard_legend_and_summary():
    out, _ = _render(_history())
    text = text_of(out)

    for expected in (
        "Powai, Mumbai - MPCB (site_1), 2025",
        "Standard: India National AQI (CPCB)",
        "published",
        "Mean AQI",
        "203.3",
        "Worst day",
        "420 Severe",
        "on 3 Jan 2025",
        "Best day",
        "Days with data",
        "3 of 365",
        "Days per category",
    ):
        assert expected in text


def test_history_of_a_month_names_it():
    sheet = workbook({"March": {5: 100}})
    out, _ = _render(_history(request=HistoryRequest(2025, month=3), sheet=sheet))

    assert "March 2025" in text_of(out)


def test_history_us_is_coloured_and_named_on_the_us_scale_only():
    out, _ = _render(_history(request=HistoryRequest(2025, standard="us")))
    text = text_of(out)
    svg = svg_of(out)

    assert "US AQI (EPA)" in text
    assert "Computed from raw" in text
    assert "India National AQI" not in text
    assert "#ff7e00" in svg
    assert "#92d050" not in svg


def test_history_india_is_not_on_the_us_scale():
    out, _ = _render(_history())
    svg = svg_of(out)

    assert "#ff9900" in svg and "#ff7e00" not in svg


def test_city_history_has_a_month_summary():
    out, _ = _render(_history("mumbai"))
    text = text_of(out)

    assert "Mumbai, Maharashtra (city average), 2025" in text
    assert "By month" in text and "January" in text


def test_saved_path_is_reported(tmp_path):
    path = tmp_path / "d.csv"
    out, _ = _render(_history(request=HistoryRequest(2025, save=str(path))))

    assert "Saved to" in " ".join(text_of(out).split())


def test_report_says_concentrations():
    request = ReportRequest(datetime(2026, 11, 8), datetime(2026, 11, 9))
    out, _ = _render(
        commands.history_report(FakeHistorical(), _place("powai"), request)
    )
    text = " ".join(text_of(out).split())

    assert "PM2.5" in text and "µg/m³" in text
    assert "concentrations, not AQI" in text
    assert "--save" in text


def test_report_of_a_city_with_a_saved_file(tmp_path):
    path = tmp_path / "r.csv"
    request = ReportRequest(
        datetime(2026, 11, 8), datetime(2026, 11, 9), save=str(path)
    )
    out = recording(120)
    render_history(
        commands.history_report(FakeHistorical(), _place("mumbai"), request), out
    )
    text = text_of(out)

    assert "Mumbai" in text and "Saved to" in text


def test_piped_output_has_no_ansi_and_keeps_category_names():
    out, _ = _render(_live("mumbai"), terminal=False)
    text = text_of(out)

    assert "\x1b[" not in text
    assert "Very Poor" in text


def test_no_color_keeps_the_text(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console = recording(80)
    console.print(scale_legend(INDIA))

    assert "Satisfactory" in text_of(console)
    assert "48;2;" not in written_to(console)


def test_piped_heatmap_keeps_band_numbers():
    out, _ = _render(_history(), terminal=False)

    assert "Jan" in text_of(out)
    assert "1 Good" in text_of(out)


def test_find_table():
    out, _ = _render(commands.find_stations(_place("anand vihar")))
    text = text_of(out)

    assert "2 stations match" in text
    assert "site_8" in text and "Delhi" in text and "28.6500" in text


def test_find_shows_a_dash_for_missing_coordinates():
    out, _ = _render(commands.find_stations(_place("solo")))

    assert "site_6" in text_of(out) and " - " in text_of(out)


def test_stations_limit_and_hint():
    result = commands.list_stations(FakeHistorical())
    out, _ = _render(result, limit=2)
    text = " ".join(text_of(out).split())

    assert "Showing 2 of 7" in text and "--all" in text
    assert text_of(out).count("site_") == 2


def test_stations_all_has_no_hint(tmp_path):
    result = commands.list_stations(FakeHistorical(), save=str(tmp_path / "s.csv"))
    out, _ = _render(result)

    assert "Showing" not in text_of(out)
    assert "Saved to" in " ".join(text_of(out).split())


def test_pm25_table():
    result = CommandResult(
        "pm25", "ok", {"year": 2020, "month": 3, "rows": [{"state": "A", "mean": 40.5}]}
    )
    out, _ = _render(result)

    assert "2020, month 3" in text_of(out) and "40.50" in text_of(out)


def test_pm25_table_for_a_year():
    result = CommandResult(
        "pm25", "ok", {"year": 2020, "month": None, "rows": [{"mean": 1.0}]}
    )
    out, _ = _render(result)

    assert "month" not in text_of(out).split("2020")[1].split("\n")[0]


def test_problems_go_to_stderr_with_a_hint():
    out, err = _render(commands.live_place(FakeLive(), _place("atlantis"), NOW))

    assert text_of(out) == ""
    assert "No station or city matches 'atlantis'" in text_of(err)
    assert "vayuayan find" in text_of(err)


@pytest.mark.parametrize(
    "status,hint",
    [
        ("network_error", "CPCB may be down"),
        ("location_unknown", "vayuayan live <place>"),
    ],
)
def test_problem_hints(status, hint):
    console = recording()
    render_problem(CommandResult("x", status, message="msg"), console)

    assert hint in text_of(console)


def test_problem_without_a_message_shows_its_status():
    console = recording()
    render_problem(CommandResult("x", "error"), console)

    assert "error" in text_of(console)


def test_ambiguous_listing_when_nobody_can_choose():
    out, err = _render(commands.live_place(FakeLive(), _place("anand vihar"), NOW))
    text = " ".join(text_of(err).split())

    assert text_of(out) == ""
    assert "Several places match" in text
    assert "Anand Vihar, Delhi - DPCC" in text
    assert "--city" in text


def test_matches_table_numbers_stations_and_cities():
    console = recording()
    render_matches(
        [
            {"kind": "city", "city": "A", "state": "B", "station_count": 2},
            {"kind": "city", "city": "C", "state": "D", "station_count": 1},
            {"kind": "station", "name": "S", "city": "E", "state": "F"},
        ],
        console,
    )
    text = text_of(console)

    assert "A (2 stations)" in text and "C (1 station)" in text
    assert "3" in text and "S" in text


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (None, "time unknown"),
        (0, "just now"),
        (45, "45 min ago"),
        (60, "1 hour ago"),
        (120, "2 hours ago"),
        (125, "2 h 5 min ago"),
    ],
)
def test_age_in_words(minutes, expected):
    assert _age(minutes) == expected


def test_clock_without_a_time():
    assert _clock(None) == "not reported"


def test_coordinates_unknown():
    assert _coordinates({"latitude": None, "longitude": 1.0}) == "not known"


def test_render_ignores_a_result_of_an_unknown_command():
    out, err = _render(CommandResult("other", "ok"))

    assert text_of(out) == "" and text_of(err) == ""
