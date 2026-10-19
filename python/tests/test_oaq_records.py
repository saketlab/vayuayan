"""OAQ daily records against the 15-minute readings, and their plots (no network)."""

from datetime import date

import pandas as pd
import pytest

from vayuayan import (
    OAQClient,
    compare_daily_records,
    daily_record_summary,
    plot_daily_record_day,
    plot_daily_record_difference,
    plot_daily_record_scatter,
    plot_daily_record_series,
    plot_daily_record_share,
    plot_daily_record_timeline,
)


def _day(sensor, day, values):
    times = pd.date_range(day, periods=len(values), freq="15min")
    return pd.DataFrame({"sensor_id": sensor, "timestamp": times, "pm25": values})


def _records(rows):
    return pd.DataFrame(rows, columns=["sensor_id", "date", "pm25"])


def test_compare_classes_each_day():
    readings = pd.concat([
        _day("s", "2026-02-10", [10.0] * 95 + [300.0]),  # record = mean
        _day("s", "2026-03-10", [10.0] * 95 + [300.0]),  # record = last
        _day("s", "2026-03-11", [20.0] * 96),  # record = mean = last
        _day("s", "2026-03-12", [10.0, None, 30.0, 50.0]),  # record = neither; NaN left out
    ])  # fmt: skip
    mean = (95 * 10 + 300) / 96
    records = _records([
        ("s", date(2026, 2, 10), round(mean, 2)),
        ("s", date(2026, 3, 10), 300.0),
        ("s", date(2026, 3, 11), 20.0),
        ("s", date(2026, 3, 12), 99.0),
        ("s", date(2026, 3, 13), 5.0),  # no readings: left out
    ])  # fmt: skip
    out = compare_daily_records(readings, records)
    assert out["class"].tolist() == ["mean", "last", "both", "neither"]
    last = out.iloc[3]
    assert (last["n"], last["mean"], last["last"], last["median"]) == (
        3,
        30.0,
        50.0,
        30.0,
    )
    assert last["last_2_mean"] == 40.0 and last["last_4_mean"] == 30.0
    assert out.loc[1, "record_is_max"] and not out.loc[0, "record_is_last"]


def test_summary_finds_the_change():
    rows = [("s", f"2026-02-{d:02d}", "mean", 30.0, 90.0) for d in (26, 27)]
    rows += [("s", f"2026-03-{d:02d}", "last", 30.0, 90.0) for d in (1, 2)]
    rows += [
        ("s", "2026-03-03", "neither", 30.0, 30.5)
    ]  # mean and last too close: not counted
    audit = pd.DataFrame(rows, columns=["sensor_id", "date", "class", "mean", "last"])
    audit["date"] = pd.to_datetime(audit["date"]).dt.date
    out = daily_record_summary(audit).iloc[0]
    assert (out["days"], out["clear_days"], out["mean"], out["last"]) == (5, 4, 2, 2)
    assert out["last_mean_day"] == date(2026, 2, 27) and out["first_last_day"] == date(
        2026, 3, 1
    )


def test_audit_leaves_out_today_and_adds_provider(monkeypatch):
    client = OAQClient.__new__(OAQClient)  # no handshake
    days = [date(2026, 3, 1), date(2026, 3, 2)]
    monkeypatch.setattr(client, "daily_records", lambda p, s, y: _records(
        [(s, d, 10.0) for d in days]))  # fmt: skip
    asked = []

    def fake_check(provider, sensor, dates, value, tolerance):
        asked.append(list(dates))
        return compare_daily_records(_day(sensor, "2026-03-01", [10.0] * 4), _records(
            [(sensor, days[0], 10.0)]))  # fmt: skip

    monkeypatch.setattr(client, "check_daily_records", fake_check)
    out = client.audit_daily_records([("cpcb", "1")], [2026], until="2026-03-02")
    assert asked == [[date(2026, 3, 1)]]
    assert out["provider"].tolist() == ["cpcb"] and out["class"].tolist() == ["both"]


@pytest.fixture
def audit():
    pytest.importorskip("matplotlib")
    rows = []
    for d in pd.date_range("2026-02-20", "2026-03-10"):
        cls = "mean" if d < pd.Timestamp("2026-03-01") else "last"
        rows.append(
            ("cpcb", "103", d.date(), cls, 50.0, 80.0, 50.0 if cls == "mean" else 80.0)
        )
    return pd.DataFrame(
        rows,
        columns=["provider", "sensor_id", "date", "class", "mean", "last", "record"],
    )


def test_plots_draw(audit):
    from matplotlib.figure import Figure

    labels = {"cpcb 103": "cpcb 103 · Delhi"}
    figures = [
        plot_daily_record_timeline(audit, change="2026-03-01", labels=labels),
        plot_daily_record_scatter(audit),
        plot_daily_record_share(audit, change="2026-03-01"),
        plot_daily_record_series(audit, "103", change="2026-03-01"),
        plot_daily_record_difference(audit, "2026-03-01", labels=labels),
    ]
    assert all(isinstance(f, Figure) and f.legends for f in figures)
    assert figures[0].axes[0].get_yticklabels()[0].get_text() == "cpcb 103 · Delhi"

    readings = _day("103", "2026-03-07", [100.0] * 60 + [20.0] * 35 + [197.39])
    check = compare_daily_records(
        readings, _records([("103", date(2026, 3, 7), 197.39)])
    )
    fig = plot_daily_record_day(readings, check)
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert texts[0].startswith("OAQ daily value 197.39 = last reading")
    assert texts[1].startswith("Mean ")
