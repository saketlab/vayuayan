"""The command line: routing, JSON output, prompts and exit codes."""

from __future__ import annotations

import json
import runpy
import sys
from datetime import datetime

import pandas as pd
import pytest

from vayuayan import cli, cli_menu, cli_parser, commands
from vayuayan.exceptions import NetworkError

from .cli_fakes import FakeHistorical, FakeLive, recording, text_of


class Harness:
    """Runs the CLI with fake clients and recording consoles."""

    def __init__(self, monkeypatch, capsys):
        self.monkeypatch = monkeypatch
        self.capsys = capsys
        self.historical = FakeHistorical()
        self.live = FakeLive()
        self.out = recording()
        self.err = recording()
        self.pm25 = []
        monkeypatch.setattr(cli, "CPCBHistorical", lambda: self.historical)
        monkeypatch.setattr(cli, "CPCBLive", lambda: self.live)
        monkeypatch.setattr(cli, "PM25Client", self._pm25_client)
        monkeypatch.setattr(cli.logging, "basicConfig", lambda **k: None)
        monkeypatch.setattr(cli, "_stdin_is_terminal", lambda: False)
        monkeypatch.setattr(cli, "_stdout_is_terminal", lambda: False)

    def _pm25_client(self, version, region):
        self.pm25.append((version, region))
        return type(
            "Client",
            (),
            {"get_pm25_stats": lambda s, *a: {"mean": 40.0}},
        )()

    def terminal(self):
        self.monkeypatch.setattr(cli, "_stdin_is_terminal", lambda: True)
        self.monkeypatch.setattr(cli, "_stdout_is_terminal", lambda: True)

    def __call__(self, *argv):
        self.out = recording()
        # Not a terminal, so no spinner frames mix with the messages under test
        self.err = recording(terminal=False)
        return cli.run(list(argv), out=self.out, err=self.err)

    @property
    def text(self):
        return text_of(self.out)

    @property
    def problem(self):
        return " ".join(text_of(self.err).split())

    def document(self):
        return json.loads(self.capsys.readouterr().out)


@pytest.fixture
def run(monkeypatch, capsys):
    return Harness(monkeypatch, capsys)


def answers(monkeypatch, *replies):
    """Answer the prompts of the CLI and the menu in order."""
    queue = list(replies)

    def ask(*args, **kwargs):
        reply = queue.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(cli.Prompt, "ask", ask)
    monkeypatch.setattr(cli.IntPrompt, "ask", ask)
    monkeypatch.setattr(cli_menu.Prompt, "ask", ask)
    return queue


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["live", "powai"], "Powai, Mumbai - MPCB"),
        (["live", "site_1"], "Powai, Mumbai - MPCB"),
        (["live", "mumbai"], "Kurla"),
        (["find", "anand", "vihar"], "site_8"),
        (["stations", "--state", "Goa"], "site_6"),
    ],
)
def test_commands_print_results(run, argv, expected):
    assert run(*argv) == 0
    assert expected in run.text


def test_multi_word_place_needs_no_quotes(run):
    assert run("live", "powai", "mumbai", "mpcb") == 0
    assert "site_1" in run.text


def test_live_with_only_a_city_filter(run):
    assert run("live", "--city", "Mumbai") == 0
    assert "Kurla" in run.text


def test_filters_narrow_the_catalogue(run):
    # site_7 is in the catalogue but not the feed, so it reads as offline
    assert run("live", "anand", "vihar", "--state", "UP") == 5
    assert "site_7" in run.text


def test_state_alone_is_a_usage_error(run):
    assert run("live", "--state", "Goa") == 2


def test_lat_without_lon_is_a_usage_error(run):
    assert run("live", "--lat", "19") == 2
    assert "--lat and --lon" in run.problem


def test_live_near_uses_given_coordinates(run):
    run.live = FakeLive(ip_down=True)

    assert run("live", "--lat", "28.6", "--lon", "77.2") == 0
    assert "ITO" in run.text


def test_year_is_taken_from_the_end_of_the_place(run):
    assert run("history", "powai", "mumbai", "2024") == 0

    assert run.historical.calls[-1][1] == ("site_1", "2024", "")


def test_default_year_is_the_last_complete_one(run):
    run("history", "powai")

    assert run.historical.calls[-1][1][1] == str(datetime.now().year - 1)


def test_a_year_after_an_option_still_counts(run):
    assert run("history", "powai", "--month", "jan", "2024") == 0

    assert run.historical.calls[-1][1][1] == "2024"


def test_history_us_goes_to_daily_aqi(run):
    assert run("history", "powai", "2025", "--standard", "us") == 0
    assert run.historical.calls[-1][2]["standard"] == "us"
    assert "US AQI" in run.text


def test_progress_of_a_slow_download_goes_to_stderr(run):
    run("history", "powai", "2025", "--standard", "us")

    assert "raw readings" in run.problem
    assert "raw readings" not in run.text.split("Source")[0]


def test_bulletin_implies_computed(run):
    assert run("history", "powai", "2025", "--bulletin") == 0
    assert run.historical.calls[-1][2]["day_ends_at"] == 16


def test_history_period_for_a_city_with_save(run, tmp_path):
    target = tmp_path / "x.csv"

    code = run(
        "history",
        "mumbai",
        "--from",
        "2025-11-08",
        "--to",
        "2025-11-09",
        "--hourly",
        "--pollutants",
        "PM2.5, NOx",
        "--save",
        str(target),
    )

    assert code == 0
    kind, args, _ = run.historical.calls[-1]
    assert kind == "city_report"
    assert args[1:5] == (
        datetime(2025, 11, 8),
        datetime(2025, 11, 10),
        "hourly",
        ("PM2.5", "NOx"),
    )
    assert target.exists()


def test_history_period_with_every(run):
    run(
        "history",
        "powai",
        "--from",
        "2026-11-08",
        "--to",
        "2026-11-09",
        "--every",
        "15min",
    )

    assert run.historical.calls[-1][1][3] == "15_minute"


@pytest.mark.parametrize(
    "argv,message",
    [
        (
            ["history", "powai", "2024", "--from", "2026-11-08", "--to", "2026-11-09"],
            "not both",
        ),
        (["history", "powai", "--from", "2026-11-08"], "both --from and --to"),
        (
            [
                "history",
                "powai",
                "--from",
                "2026-11-08",
                "--to",
                "2026-11-09",
                "--standard",
                "us",
            ],
            "do not combine",
        ),
    ],
)
def test_conflicting_history_options_are_usage_errors(run, argv, message):
    assert run(*argv) == 2
    assert message in run.problem


def test_find_save(run, tmp_path):
    target = tmp_path / "f.csv"

    assert run("find", "anand", "vihar", "--save", str(target)) == 0
    assert len(pd.read_csv(target)) == 2


def test_stations_limits_people_but_not_json(run, capsys):
    assert run("stations", "--limit", "2") == 0
    assert "Showing 2 of 7" in " ".join(run.text.split())

    assert run("stations", "--limit", "2", "--json") == 0
    assert len(run.document()["stations"]) == 7


def test_stations_all_shows_everything(run):
    assert run("stations", "--all") == 0
    assert "Showing" not in run.text


def test_pm25(run):
    assert run("pm25", "a.geojson", "2020", "--month", "3", "--region", "AS") == 0
    assert run.pm25 == [("V6GL03", "AS")]
    assert "40.00" in run.text


@pytest.mark.parametrize(
    "command",
    [
        "list_states",
        "list_cities",
        "list_stations",
        "daily_aqi",
        "nearest_station",
        "live_aqi",
        "station_table",
        "city_report",
        "city_data",
        "station_data",
        "locate_me",
    ],
)
def test_old_commands_are_gone(run, command):
    assert run(command) == 2


@pytest.mark.parametrize(
    "argv,code",
    [
        (["live", "atlantis"], 3),
        (["history", "atlantis", "2025"], 3),
        (["find", "atlantis"], 3),
        (["stations", "--city", "Atlantis"], 3),
        (["live", "anand", "vihar"], 4),
        (["history", "anand", "vihar", "2025"], 4),
        (["live", "colaba"], 5),
        (["nonsense"], 2),
        (["live", "--nope"], 2),
        (["history"], 2),
        (["history", "powai", "--month", "13"], 2),
        (["history", "powai", "--from", "yesterday", "--to", "2026-01-01"], 2),
    ],
)
def test_exit_codes(run, argv, code):
    assert run(*argv) == code


def test_a_year_without_data_exits_5(run):
    run.historical = FakeHistorical(no_data=True)

    assert run("history", "powai", "2030") == 5
    assert "Data not found" in run.problem


def test_cpcb_outage_exits_6_with_a_short_message(run):
    run.live = FakeLive(down=True)

    assert run("live", "powai") == 6
    assert "Could not reach CPCB" in run.text
    assert "Traceback" not in run.text + run.problem


def test_catalogue_failure_exits_6(run):
    class Down(FakeHistorical):
        def station_table(self, state="", city=""):
            raise NetworkError("down")

    run.historical = Down()

    assert run("find", "powai") == 6


def test_unexpected_error_is_short_without_debug(run):
    def boom(*args):
        raise RuntimeError("boom")

    run.monkeypatch.setattr(commands, "lookup_place", boom)

    assert run("find", "x") == 1
    assert "Something went wrong: boom" in run.problem
    assert "Traceback" not in run.problem


def test_debug_shows_the_traceback(run):
    def boom(*args):
        raise RuntimeError("boom")

    run.monkeypatch.setattr(commands, "lookup_place", boom)

    assert run("find", "x", "--debug") == 1
    assert "Traceback" in run.problem


def test_ctrl_c_stops_quietly(run):
    def stop(*args):
        raise KeyboardInterrupt

    run.monkeypatch.setattr(commands, "lookup_place", stop)

    assert run("find", "x") == 130
    assert run.problem == "Stopped."


def test_json_is_one_document_and_nothing_else(run):
    code = run("live", "powai", "--json")
    document = run.document()

    assert code == 0
    assert document["status"] == "ok" and document["command"] == "live"
    assert document["reading"]["station"]["id"] == "site_1"
    assert run.text == ""


def test_json_flag_works_before_the_command(run):
    run("--json", "find", "powai")

    assert run.document()["count"] == 1


def test_json_ambiguous_schema(run):
    assert run("live", "anand", "vihar", "--json") == 4

    document = run.document()
    assert document["status"] == "ambiguous"
    assert [m["id"] for m in document["matches"]] == ["site_8", "site_7"]
    assert run.problem == ""


def test_json_not_found(run):
    assert run("live", "atlantis", "--json") == 3
    assert run.document()["status"] == "not_found"


def test_json_usage_error_is_json_too(run):
    assert run("nonsense", "--json") == 2
    assert run.document()["status"] == "usage_error"


def test_json_handler_usage_error(run):
    assert run("live", "--state", "Goa", "--json") == 2
    assert run.document()["status"] == "usage_error"


def test_json_failure_with_an_exception(run):
    def boom(*args):
        raise RuntimeError("boom")

    run.monkeypatch.setattr(commands, "lookup_place", boom)

    assert run("find", "x", "--json") == 1
    assert run.document()["status"] == "error"


def test_json_never_prompts_in_a_terminal(run, monkeypatch):
    run.terminal()
    answers(monkeypatch)

    assert run("live", "anand", "vihar", "--json") == 4


def test_no_input_never_prompts_in_a_terminal(run, monkeypatch):
    run.terminal()
    answers(monkeypatch)

    assert run("live", "anand", "vihar", "--no-input") == 4


def test_ambiguous_in_a_terminal_asks_and_continues(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, 1)

    assert run("find", "anand", "vihar") == 0
    assert run("live", "anand", "vihar") in (0, 5)
    assert "Anand Vihar, Delhi" in run.problem


def test_ambiguous_choice_applies_to_the_command(run, monkeypatch):
    run.terminal()
    run.live = FakeLive()
    answers(monkeypatch, 2)

    run("history", "anand", "vihar", "2025")

    assert run.historical.calls[-1][1][0] == "site_7"


def test_us_for_a_city_lets_the_user_pick_a_station(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, 3)

    assert run("history", "mumbai", "2025", "--standard", "us") == 0
    assert run.historical.calls[-1][0] == "daily_aqi"
    assert run.historical.calls[-1][1][0] == "site_1"


def test_us_for_a_city_is_ambiguous_without_a_terminal(run):
    assert run("history", "mumbai", "2025", "--standard", "us") == 4
    assert "Pick a station" in run.problem


def test_ctrl_c_at_a_prompt_stops_quietly(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, KeyboardInterrupt())

    assert run("live", "anand", "vihar") == 130


def test_ip_failure_asks_for_a_place_in_a_terminal(run, monkeypatch):
    run.terminal()
    run.live = FakeLive(ip_down=True)
    answers(monkeypatch, "powai")

    assert run("live") == 0
    assert "Powai" in run.text
    assert "Could not work out your location" in run.problem


def test_ip_failure_with_an_empty_reply_gives_up(run, monkeypatch):
    run.terminal()
    run.live = FakeLive(ip_down=True)
    answers(monkeypatch, "")

    assert run("live") == 6


def test_ip_failure_without_a_terminal_says_what_to_do(run):
    run.live = FakeLive(ip_down=True)

    assert run("live") == 6
    assert "vayuayan live <place>" in run.problem


def test_ip_address_is_never_printed(run):
    run.live.location = (19.1, 72.9)

    run("live")

    assert "19.1," not in run.text.split("Station")[0]


def test_near_me_succeeds(run):
    assert run("live") == 0
    assert "Nearest to your location" in " ".join(run.text.split())


def test_no_command_without_a_terminal_prints_help_and_exits_2(run):
    assert run() == 2
    assert "vayuayan CLI" in run.text


def test_no_command_with_json_is_a_usage_error(run):
    assert run("--json") == 2
    assert run.document()["message"] == "no command given"


def test_no_input_without_a_command_prints_help(run):
    run.terminal()

    assert run("--no-input") == 2


def test_menu_runs_each_choice_until_quit(run, monkeypatch):
    run.terminal()
    answers(
        monkeypatch,
        "1",
        "2",
        "powai",
        "3",
        "powai",
        "2024",
        "3",
        "powai",
        "",
        "4",
        "anand vihar",
        "5",
    )

    assert run() == 0
    calls = [c for c in run.historical.calls if c[0] == "station_year"]
    assert [c[1][1] for c in calls] == ["2024", str(datetime.now().year - 1)]
    assert "site_8" in run.text


def test_menu_blank_place_returns_to_the_menu(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, "2", "", "5")

    assert run() == 0
    assert run.historical.calls == []


def test_menu_bad_input_does_not_end_the_menu(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, "2", "--nope", "5")

    assert run() == 0
    assert "unrecognised" in run.problem or "error" in run.problem


def test_menu_ctrl_c_ends_it(run, monkeypatch):
    run.terminal()
    answers(monkeypatch, KeyboardInterrupt())

    assert run() == 130


def test_spinner_runs_on_a_terminal_stderr(run):
    err = recording()

    assert (
        cli.run(["history", "powai", "2025", "--standard", "us"], recording(), err) == 0
    )
    assert "raw readings" in text_of(err)


def test_progress_without_a_terminal_is_plain_text(run):
    run.err = recording(terminal=False)

    assert (
        cli.run(["history", "powai", "2025", "--standard", "us"], run.out, run.err) == 0
    )
    assert "raw readings" in text_of(run.err)


def test_stdin_and_stdout_checks_use_the_real_streams(monkeypatch):
    class Stream:
        @staticmethod
        def isatty():
            return True

    from importlib import reload

    fresh = reload(cli)
    monkeypatch.setattr(sys, "stdin", Stream())
    monkeypatch.setattr(sys, "stdout", Stream())

    assert fresh._stdin_is_terminal() and fresh._stdout_is_terminal()


def test_library_logs_at_warning_and_debug_at_debug(monkeypatch, capsys):
    harness = Harness(monkeypatch, capsys)
    configured = []
    monkeypatch.setattr(cli.logging, "basicConfig", lambda **k: configured.append(k))

    harness("find", "powai")
    harness("find", "powai", "--debug")

    assert configured[0]["level"] == cli.logging.WARNING
    assert configured[1]["level"] == cli.logging.DEBUG
    assert configured[0]["stream"] is sys.stderr


def test_help_shows_examples_exit_codes_and_the_privacy_note(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["vayuayan", "--help"])

    with pytest.raises(SystemExit) as stop:
        cli.run()

    out = capsys.readouterr().out
    assert stop.value.code == 0
    assert "Examples:" in out and "Exit codes:" in out
    assert "ip-api.com" in out
    for code in ("3 ", "4 ", "5 ", "6 "):
        assert code in out


def test_live_help_mentions_ip_api(capsys):
    with pytest.raises(SystemExit):
        cli.run(["live", "--help"])

    assert "ip-api.com" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.run(["--version"])

    assert stop.value.code == 0
    assert capsys.readouterr().out.strip()


def test_main_exits_with_the_code_of_run(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda: 4)

    with pytest.raises(SystemExit) as stop:
        cli.main()

    assert stop.value.code == 4


def test_main_treats_a_closed_pipe_as_success(monkeypatch, tmp_path):
    def closed():
        raise BrokenPipeError

    stream = open(tmp_path / "out.txt", "w")
    monkeypatch.setattr(cli, "run", closed)
    monkeypatch.setattr(sys, "stdout", stream)

    with pytest.raises(SystemExit) as stop:
        cli.main()

    stream.close()
    assert stop.value.code == 0


def test_a_closed_pipe_is_not_reported_as_an_error(run):
    def closed(*args):
        raise BrokenPipeError

    run.monkeypatch.setattr(commands, "lookup_place", closed)

    with pytest.raises(BrokenPipeError):
        run("find", "x")


def test_python_dash_m_runs_the_cli(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vayuayan", "--help"])

    with pytest.raises(SystemExit) as stop:
        runpy.run_module("vayuayan", run_name="__main__", alter_sys=True)

    assert stop.value.code == 0
    assert "vayuayan CLI" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text,expected",
    [("3", 3), ("march", 3), ("Mar", 3), ("12", 12)],
)
def test_month_number(text, expected):
    assert cli_parser.month_number(text) == expected


@pytest.mark.parametrize("text", ["0", "13", "smarch"])
def test_month_number_rejects_others(text):
    with pytest.raises(cli_parser.argparse.ArgumentTypeError):
        cli_parser.month_number(text)


def test_start_time():
    assert cli_parser.start_time("2026-11-08 09:30") == datetime(2026, 11, 8, 9, 30)


def test_a_bare_end_date_covers_the_whole_day():
    now = datetime(2026, 12, 1, 15, 45)

    assert cli_parser.end_time("2026-11-09", now) == datetime(2026, 11, 10)


def test_an_end_time_is_kept():
    now = datetime(2026, 12, 1, 15, 45)

    assert cli_parser.end_time("2026-11-09 06:00", now) == datetime(2026, 11, 9, 6)


def test_an_end_in_the_future_stops_at_the_last_whole_hour():
    now = datetime(2026, 11, 9, 15, 45)

    assert cli_parser.end_time("2026-11-09", now) == datetime(2026, 11, 9, 15)
