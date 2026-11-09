"""Which repository files the historical client picks and where it caches them."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from vayuayan import CPCBHistorical
from vayuayan.exceptions import DataNotFoundError


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/AQI/2020/x.csv", "AQI/2020/x.csv"),
        ("/AQI/../2020/./x.csv", "AQI/2020/x.csv"),
        ("/AQI/2020/a b&c.csv", "AQI/2020/a_b_c.csv"),
        ("../AQI_Bulletin/2020-2021/city.xlsx", "AQI_Bulletin/2020-2021/city.xlsx"),
    ],
)
def test_cache_path_stays_inside_the_cache(tmp_path, path, expected):
    client = CPCBHistorical(cache_dir=str(tmp_path))

    assert client._cache_path(path) == tmp_path.joinpath(*expected.split("/"))


def test_cache_path_is_none_when_the_file_must_not_be_cached(tmp_path):
    client = CPCBHistorical(cache_dir=str(tmp_path))

    assert client._cache_path("/AQI/no_year.csv") is None
    assert client._cache_path(f"/AQI/{date.today().year}/x.csv") is None
    # a year range counts as its later year
    this_year = date.today().year
    assert client._cache_path(f"/AQI/{this_year - 1}-{this_year}/x.csv") is None
    assert client._cache_path(f"/AQI/{this_year - 2}-{this_year - 1}/x.csv") is not None
    assert CPCBHistorical(use_cache=False)._cache_path("/AQI/2020/x.csv") is None


def test_select_entries_by_month_field_or_path():
    entries = [
        {"month": "January", "filepath": "/a"},
        {"filepath": "/2024/February/b"},
        {"month": "March", "filepath": "/c"},
    ]
    select = CPCBHistorical()._select_repository_entry

    assert select(entries, "2024", "JANUARY") == [entries[0]]
    assert select(entries, "2024", "february") == [entries[1]]
    assert select(entries, "2024", "December") == []


def test_select_entries_never_uses_another_year():
    entries = [{"year": "2023"}, {"year": 2024}, {"filepath": "/undated"}]
    select = CPCBHistorical()._select_repository_entry

    assert select(entries, "2024") == [entries[1], entries[2]]
    assert select(entries, "1999") == [entries[2]]
    assert select(entries[:2], "1999") == []


def test_select_entries_by_month_ignores_the_station_name():
    entries = [
        {"month": "January", "filepath": "/2024/January/Mayapuri_January.xlsx"},
        {"month": "May", "filepath": "/2024/May/Mayapuri_May.xlsx"},
    ]

    selected = CPCBHistorical()._select_repository_entry(entries, "2024", "May")

    assert selected == [entries[1]]


def test_combine_excels_raises_when_nothing_matches():
    client = CPCBHistorical()

    with pytest.raises(DataNotFoundError, match="2024 and month June"):
        client._combine_repository_excels(
            [{"month": "May", "filepath": "/May"}], "2024", "June"
        )
    with pytest.raises(DataNotFoundError, match="2024"):
        client._combine_repository_excels([], "2024")


def test_combine_excels_raises_when_no_entry_has_a_file():
    with pytest.raises(DataNotFoundError, match="No downloadable"):
        CPCBHistorical()._combine_repository_excels([{"year": "2024"}], "2024")


def test_combine_excels_keeps_the_month_and_year_columns_of_the_file():
    client = CPCBHistorical()
    client._read_repository_excel = lambda path: pd.DataFrame(
        {"Year": [1999], "Month": ["Own"], "Day": [1]}
    )

    df = client._combine_repository_excels(
        [{"filepath": "/x", "year": "2024", "month": "May"}], "2024"
    )

    assert df.to_dict("records") == [{"Year": 1999, "Month": "Own", "Day": 1}]


def test_read_year_excel_compares_years_as_text():
    client = CPCBHistorical()
    client._read_repository_excel = lambda path: pd.DataFrame({"path": [path]})
    entries = [{"year": 2023, "filepath": "/a"}, {"year": 2024, "filepath": "/b"}]

    assert client._read_year_excel(entries, "2024")["path"].tolist() == ["/b"]
    assert client._read_year_excel(entries, "2025") is None
