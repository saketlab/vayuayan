"""Online parity: the R and Python packages must return the same live data.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List

import pytest

REPO = Path(__file__).resolve().parents[1]
COORDS = (28.61, 77.21)

pytestmark = pytest.mark.skipif(
    os.environ.get("VAYUAYAN_ONLINE") != "1" or shutil.which("Rscript") is None,
    reason="set VAYUAYAN_ONLINE=1 (and install R) to call the live services",
)


def norm(x: Any) -> Any:
    """Python results in the JSON shape of parity/online.R."""
    import numpy as np
    import pandas as pd

    if isinstance(x, pd.DataFrame):
        return {c: norm(x[c].tolist()) for c in x.columns}
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [norm(v) for v in x]
    if isinstance(x, np.generic):
        return norm(x.item())
    if isinstance(x, float) and math.isnan(x):
        return None
    if x is pd.NaT or x is pd.NA:
        return None
    return x


def differences(py: Any, r: Any, where: str = "") -> Iterator[str]:
    """Where py and r differ; numbers to a relative 1e-6."""
    # jsonlite writes length-1 vectors as scalars
    if isinstance(py, list) and len(py) == 1 and not isinstance(r, list):
        py = py[0]
    if isinstance(r, list) and len(r) == 1 and not isinstance(py, list):
        r = r[0]
    if isinstance(py, dict) and isinstance(r, dict):
        if set(py) != set(r):
            yield (
                f"{where}: keys only in Python {sorted(set(py) - set(r))}, "
                f"only in R {sorted(set(r) - set(py))}"
            )
        for k in sorted(set(py) & set(r)):
            yield from differences(py[k], r[k], f"{where}.{k}")
    elif isinstance(py, list) and isinstance(r, list):
        if len(py) != len(r):
            yield f"{where}: {len(py)} items in Python, {len(r)} in R"
        bad = [i for i, (a, b) in enumerate(zip(py, r)) if any(differences(a, b))]
        if bad:
            i = bad[0]
            yield f"{where}[{i}] (+{len(bad) - 1} more): Python {py[i]!r}, R {r[i]!r}"
    elif isinstance(py, (int, float)) and isinstance(r, (int, float)):
        if not math.isclose(py, r, rel_tol=1e-6, abs_tol=1e-9):
            yield f"{where}: Python {py!r}, R {r!r}"
    elif py != r:
        yield f"{where}: Python {py!r}, R {r!r}"


def python_cases(cache: Path, polygon: Path) -> Dict[str, Callable[[], Any]]:
    """The cases of parity/online.R, called through the Python package."""
    import pandas as pd
    import vayuayan as v

    hist = v.CPCBHistorical(cache_dir=str(cache / "root" / "cpcb"))
    live = v.CPCBLive()
    csv = str(cache / "csv")
    pm25 = v.PM25Client("V6GL03", cache_dir=str(cache / "pm25"), region="AS")
    now = datetime.now().strftime("%Y-%m-%dT%H:00:00Z")
    client = v.CPCBClient()

    def nearest() -> List[Any]:
        return client.get_k_nearest_stations(*COORDS, k=5)

    cases: Dict[str, Callable[[], Any]] = {
        "state_list": hist.get_state_list,
        "city_list": lambda: hist.get_city_list("Maharashtra"),
        "station_list": lambda: _columns(hist.get_station_list("Delhi")),
        "add_coords": lambda: _columns(hist.add_coords(hist.get_station_list("Delhi"))),
        "file_path_station": lambda: hist.get_file_path(
            "site_301", "", "", "", "2023", "daily", "stationLevel"
        ),
        "file_path_city": lambda: hist.get_file_path(
            "", "", "", "Delhi", "", "daily", "cityLevel"
        ),
        "city_daily": lambda: hist.city_daily("Delhi", 2023, cache_dir=csv),
        "station_daily": lambda: hist.station_daily("site_301", 2023, cache_dir=csv),
        "station_daily_aqi": lambda: hist.daily_aqi("site_301", "2023"),
        "raw_station": lambda: hist.download_raw_aqi_data_station_level(
            "site_301", "2023", "", tidy=True
        ),
        "hourly_city": lambda: hist.download_hourly_aqi_data_city_level(
            "Delhi", "2023", "", month="January"
        ),
        "hourly_station": lambda: hist.download_hourly_aqi_data_station_level(
            "site_301", "2023", "", month="January"
        ),
        # Python returns tuples, R named lists; compare id, name and distance
        "nearest_station": lambda: {
            "station_id": live.get_nearest_station(COORDS)[0],
            "station_name": live.get_nearest_station(COORDS)[1],
            "distance_km": v.CPCBClient().get_nearest_station(
                *COORDS, return_distance=True
            )[1],
        },
        "nearest_stations": lambda: {
            "station_id": [s["id"] for s, _ in nearest()],
            "station_name": [s["name"] for s, _ in nearest()],
            "distance_km": [d for _, d in nearest()],
        },
        "nearest_within_radius": lambda: list(
            v.CPCBClient().get_nearest_station_within_radius(*COORDS, 3) or []
        ),
        "all_india": lambda: v.stations_to_dataframe(live.get_all_india()),
        "live_station": lambda: _live(
            live.get_live_aqi_data_for_station("site_301", now)
        ),
        "india_boundary": lambda: list(v.india_boundary(state="Delhi").bounds),
        "pm25_point": lambda: pm25.get_pm25_at_point(*COORDS, 2020),
        "pm25_point_monthly": lambda: pm25.get_pm25_at_point(*COORDS, 2020, month=1),
        "pm25_stats": lambda: pm25.get_pm25_stats(str(polygon), 2020),
    }
    if os.environ.get("OAQ_API_KEY"):
        # jsonlite simplifies the records to a data frame, so compare as a table
        cases["oaq_providers"] = lambda: {
            "providers": pd.DataFrame(v.OAQClient().list_providers()["providers"])
        }
        cases["oaq_stations"] = lambda: v.OAQClient().stations_table("cpcb")
        cases["oaq_tally"] = lambda: v.oaq_city_tally(v.OAQClient().sensors())
        cases["oaq_check_records"] = lambda: v.OAQClient().check_daily_records(
            "cpcb", "164", ["2026-05-29", "2026-05-30"]
        )
        cases["oaq_readings"] = lambda: v.OAQClient().readings(
            "airnet", "12036", ["2026-09-14", "2026-09-15"]
        )
        cases["oaq_daily_means"] = lambda: v.OAQClient().daily_means(
            "airnet", "12032", ["2026-09-14", "2026-09-15"]
        )
    return cases


def _columns(rows: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    return {k: [row.get(k) for row in rows] for k in (rows[0] if rows else {})}


def _live(data: Dict[str, Any]) -> Dict[str, Any]:
    import vayuayan as v

    return {
        "station_id": data.get("station_id"),
        "station_name": data.get("station_name"),
        "metrics": v.live_metrics(data),
    }


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """Polygon input, and the R results from one run of online.R."""
    import geopandas as gpd
    import vayuayan as v

    base = tmp_path_factory.mktemp("parity")
    polygon = base / "delhi.geojson"
    if "pm25_stats" in CASE_NAMES:
        gpd.GeoDataFrame(
            {"name": ["Delhi"]}, geometry=[v.india_boundary(state="Delhi")], crs=4326
        ).to_file(polygon, driver="GeoJSON")
    out = base / "r.json"
    subprocess.run(
        ["Rscript", "parity/online.R", str(out), str(base / "r"), str(polygon)],
        cwd=REPO,
        check=True,
        timeout=3600,
    )
    py = python_cases(base / "py", polygon)
    return {
        "r": json.loads(out.read_text(encoding="utf-8")),
        "py": {k: f for k, f in py.items() if k in CASE_NAMES},
    }


CASE_NAMES = [
    "state_list", "city_list", "station_list", "add_coords",
    "file_path_station", "file_path_city", "city_daily", "station_daily",
    "station_daily_aqi", "raw_station", "hourly_city", "hourly_station",
    "nearest_station", "nearest_stations", "nearest_within_radius",
    "all_india", "live_station",
    "india_boundary", "pm25_point", "pm25_point_monthly", "pm25_stats",
]  # fmt: skip
if os.environ.get("OAQ_API_KEY"):
    CASE_NAMES += [
        "oaq_providers",
        "oaq_stations",
        "oaq_tally",
        "oaq_daily_means",
        "oaq_readings",
        "oaq_check_records",
    ]
_ONLY = [p for p in os.environ.get("PARITY_ONLY", "").split(",") if p]
if _ONLY:
    CASE_NAMES = [n for n in CASE_NAMES if n.startswith(tuple(_ONLY))]


def test_both_languages_have_every_case(setup: Dict[str, Any]) -> None:
    assert sorted(setup["r"]) == sorted(setup["py"]) == sorted(CASE_NAMES)


@pytest.mark.parametrize("name", CASE_NAMES)
def test_same_result(setup: Dict[str, Any], name: str) -> None:
    r = setup["r"][name]
    try:
        py = norm(setup["py"][name]())
    except Exception as e:  # noqa: BLE001 - report the failure next to R's
        assert "error" in r, f"Python failed ({type(e).__name__}: {e}); R did not"
        pytest.fail(f"both failed: Python {type(e).__name__}: {e}; R {r['error']}")
    assert "error" not in r, f"R failed: {r['error']}"
    diffs = list(differences(py, r["value"], name))
    assert not diffs, "\n".join(diffs[:20])
