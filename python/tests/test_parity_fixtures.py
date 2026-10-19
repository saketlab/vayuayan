"""The R parity fixtures must match what the Python package returns now."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

import vayuayan

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "make_parity_fixtures.py"
)
SPEC = importlib.util.spec_from_file_location("make_parity_fixtures", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
make_parity_fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_parity_fixtures)

REPO = Path(__file__).resolve().parents[2]
STALE = "R parity fixtures are stale; run python scripts/make_parity_fixtures.py"

pytestmark = pytest.mark.skipif(
    not make_parity_fixtures.FIXTURES.is_dir(), reason="needs the monorepo's R/ folder"
)


def test_parity_json_is_current() -> None:
    committed = json.loads(make_parity_fixtures.JSON_PATH.read_text(encoding="utf-8"))
    current = json.loads(make_parity_fixtures.dumps(make_parity_fixtures.build()))
    assert committed == current, STALE


def test_daily_aqi_csv_is_current() -> None:
    committed = make_parity_fixtures.DAILY_OUTPUT.read_text(encoding="utf-8")
    assert committed == make_parity_fixtures.build_daily_csv(), STALE


def _public_api() -> set:
    """Public functions, and public methods of the public classes."""
    names = set()
    for name in vayuayan.__all__:
        obj = getattr(vayuayan, name)
        if inspect.isfunction(obj):
            names.add(name)
        elif inspect.isclass(obj) and not issubclass(obj, Exception):
            names.update(
                f"{name}.{m}"
                for m, _ in inspect.getmembers(obj, inspect.isfunction)
                if not m.startswith("_")
            )
    return names


def test_every_public_name_is_mapped_to_r() -> None:
    mapped = set(make_parity_fixtures.API) | set(make_parity_fixtures.PYTHON_ONLY)
    missing = _public_api() - mapped - {"OAQClient.__init__"}
    assert not missing, f"add to API or PYTHON_ONLY in make_parity_fixtures: {missing}"


def test_mapped_names_exist() -> None:
    for name in [*make_parity_fixtures.API, *make_parity_fixtures.PYTHON_ONLY]:
        obj = vayuayan
        for part in name.split("."):
            obj = getattr(obj, part)


def test_station_snapshots_are_identical() -> None:
    python = REPO / "python" / "vayuayan" / "data" / "cpcb_station_directory.json"
    r = REPO / "R" / "inst" / "extdata" / "cpcb_station_directory.json"
    assert python.read_bytes() == r.read_bytes(), "copy the snapshot to R/inst/extdata"
