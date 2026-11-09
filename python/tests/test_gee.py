"""Google Earth Engine setup, project lookup and download, with a stub ee module."""

from __future__ import annotations

import builtins
import io
import sys
import zipfile
from unittest.mock import MagicMock

import pytest

from vayuayan import gee

from .fakes import http_response

MONTHLY = "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25/MONTHLY"
DOWNLOAD_URL = "https://earthengine.example/download"


@pytest.fixture
def ee(monkeypatch):
    stub = MagicMock(name="ee")
    stub.Filter.calendarRange.side_effect = lambda a, b, unit: ("range", a, b, unit)
    stub.Filter.And.side_effect = lambda *parts: ("and", *parts)
    monkeypatch.setitem(sys.modules, "ee", stub)
    monkeypatch.setattr(gee, "is_available", lambda: True)
    return stub


@pytest.fixture
def project_file(monkeypatch, tmp_path):
    path = tmp_path / "gee_project"
    monkeypatch.setattr(gee, "get_gee_project_file", lambda: path)
    return path


@pytest.fixture(autouse=True)
def _terminal(monkeypatch):
    """Setup prompts only at a terminal; tests of a script set isatty to False."""
    monkeypatch.setattr(sys, "stdin", MagicMock(isatty=lambda: True))


def test_is_available_looks_for_the_package(monkeypatch):
    monkeypatch.setattr(gee.importlib.util, "find_spec", lambda name: object())
    assert gee.is_available() is True

    monkeypatch.setattr(gee.importlib.util, "find_spec", lambda name: None)
    assert gee.is_available() is False


def test_setup_without_the_library_explains_the_install(monkeypatch, capsys):
    monkeypatch.setattr(gee, "is_available", lambda: False)

    assert gee.setup_earth_engine() is False
    assert "pip install earthengine-api" in capsys.readouterr().out


def test_setup_with_a_project_uses_working_credentials(ee, project_file, capsys):
    ee.ImageCollection.return_value.size.return_value.getInfo.return_value = 12

    assert gee.setup_earth_engine("my-project") is True

    ee.Authenticate.assert_not_called()
    ee.Initialize.assert_called_once_with(project="my-project")
    ee.ImageCollection.assert_called_once_with(MONTHLY)
    assert project_file.read_text() == "my-project"
    assert "12 images" in capsys.readouterr().out


def test_setup_asks_for_the_project(ee, project_file, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda prompt: "  asked-project \n")

    assert gee.setup_earth_engine() is True

    assert project_file.read_text() == "asked-project"
    assert "Already authenticated" in capsys.readouterr().out


def test_setup_still_asks_when_the_first_initialize_fails(
    ee, project_file, monkeypatch
):
    ee.Initialize.side_effect = [RuntimeError("no credentials"), None]
    monkeypatch.setattr(builtins, "input", lambda prompt: "asked")

    assert gee.setup_earth_engine() is True
    assert project_file.read_text() == "asked"


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_setup_can_be_cancelled_at_the_prompt(ee, project_file, monkeypatch, error):
    def cancel(prompt):
        raise error

    monkeypatch.setattr(builtins, "input", cancel)

    assert gee.setup_earth_engine() is False
    assert not project_file.exists()
    ee.Authenticate.assert_not_called()


def test_setup_needs_a_project_id(ee, project_file, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "   ")

    assert gee.setup_earth_engine() is False
    ee.Authenticate.assert_not_called()


@pytest.mark.parametrize(
    "error,printed",
    [(KeyboardInterrupt(), "Setup cancelled"), (RuntimeError("denied"), "denied")],
)
def test_setup_failure_saves_nothing(ee, project_file, capsys, error, printed):
    ee.Initialize.side_effect = RuntimeError("not signed in")
    ee.Authenticate.side_effect = error

    assert gee.setup_earth_engine("p") is False
    assert not project_file.exists()
    assert printed in capsys.readouterr().out


@pytest.fixture
def clean_project(monkeypatch, tmp_path, project_file):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    return project_file


def test_project_id_prefers_the_environment(clean_project, monkeypatch):
    monkeypatch.setenv("GEE_PROJECT", "from-gee")
    assert gee.project_id() == "from-gee"

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "from-cloud")
    assert gee.project_id() == "from-cloud"


def test_project_id_reads_the_config_file(clean_project):
    clean_project.write_text(" from-config\n")

    assert gee.project_id() == "from-config"


def test_project_id_is_none_when_nothing_is_set(clean_project):
    assert gee.project_id() is None


def test_project_id_migrates_the_legacy_file(clean_project, tmp_path):
    (tmp_path / ".gee_project").write_text("legacy\n")

    assert gee.project_id() == "legacy"
    assert clean_project.read_text() == "legacy"


def test_project_id_survives_a_failed_migration(clean_project, tmp_path, monkeypatch):
    (tmp_path / ".gee_project").write_text("legacy")
    monkeypatch.setattr(
        gee, "get_gee_project_file", lambda: tmp_path / "missing" / "gee_project"
    )

    assert gee.project_id() == "legacy"


def test_initialize_tries_the_high_volume_endpoint_first(ee, monkeypatch):
    monkeypatch.setattr(gee, "project_id", lambda: "p")

    assert gee.initialize() is True

    ee.Initialize.assert_called_once_with(
        project="p", opt_url="https://earthengine-highvolume.googleapis.com"
    )


def test_initialize_falls_through_the_attempts(ee, monkeypatch):
    monkeypatch.setattr(gee, "project_id", lambda: "p")
    ee.Initialize.side_effect = [
        RuntimeError("a"),
        RuntimeError("b"),
        RuntimeError("c"),
        None,
    ]

    assert gee.initialize() is True

    assert [c.kwargs for c in ee.Initialize.call_args_list] == [
        {"project": "p", "opt_url": "https://earthengine-highvolume.googleapis.com"},
        {"project": "p"},
        {"project": "earthengine-legacy"},
        {},
    ]


def test_initialize_without_a_project_tries_the_defaults(ee, monkeypatch):
    monkeypatch.setattr(gee, "project_id", lambda: None)
    ee.Initialize.side_effect = RuntimeError("no")

    assert gee.initialize() is False
    assert [c.kwargs for c in ee.Initialize.call_args_list] == [
        {"project": "earthengine-legacy"},
        {},
    ]


def _zip_with(*names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"tif-bytes")
    return buffer.getvalue()


def _image(ee):
    image = ee.ImageCollection.return_value.filter.return_value.first.return_value
    image.clip.return_value.getDownloadURL.return_value = DOWNLOAD_URL
    return image


def test_download_writes_the_tif_of_the_archive(ee, network, tmp_path):
    image = _image(ee)
    region = ee.Geometry.Rectangle.return_value
    network.on("get", DOWNLOAD_URL, http_response(_zip_with("sub.tif", "notes.txt")))
    output = tmp_path / "out.tif"

    result = gee.download_geotiff("collection", 2020, 3, output)

    assert result == str(output)
    assert output.read_bytes() == b"tif-bytes"
    assert not output.with_suffix(".zip").exists()
    ee.ImageCollection.assert_called_once_with("collection")
    filtered = ee.ImageCollection.return_value.filter.call_args.args[0]
    assert filtered == (
        "and",
        ("range", 2020, 2020, "year"),
        ("range", 3, 3, "month"),
    )
    ee.Geometry.Rectangle.assert_called_once_with([68.0, 8.0, 98.0, 37.0])
    image.clip.assert_called_once_with(region)
    options = image.clip.return_value.getDownloadURL.call_args.args[0]
    assert options == {
        "scale": 10000,
        "crs": "EPSG:4326",
        "fileFormat": "GeoTIFF",
        "region": region,
    }
    assert network.calls[0].kwargs["stream"] is True


def test_download_of_an_annual_image_uses_the_year_and_given_region(
    ee, network, tmp_path
):
    image = _image(ee)
    network.on("get", DOWNLOAD_URL, http_response(_zip_with("a.tif")))

    assert gee.download_geotiff("c", 2020, None, tmp_path / "a2.tif", "region")

    filtered = ee.ImageCollection.return_value.filter.call_args.args[0]
    assert filtered == ("range", 2020, 2020, "year")
    ee.Geometry.Rectangle.assert_not_called()
    image.clip.assert_called_once_with("region")


def test_download_without_an_image_is_none(ee, tmp_path):
    ee.ImageCollection.return_value.filter.return_value.first.return_value = None

    assert gee.download_geotiff("c", 2020, 1, tmp_path / "x.tif") is None


def test_download_of_an_archive_without_a_tif_leaves_nothing(ee, network, tmp_path):
    _image(ee)
    network.on("get", DOWNLOAD_URL, http_response(_zip_with("readme.txt")))
    output = tmp_path / "x.tif"

    assert gee.download_geotiff("c", 2020, 1, output) is None
    assert list(tmp_path.iterdir()) == []


def test_earth_engine_error_is_none_and_leaves_nothing(ee, tmp_path):
    ee.ImageCollection.side_effect = RuntimeError("quota")

    assert gee.download_geotiff("c", 2020, 1, tmp_path / "x.tif") is None
    assert list(tmp_path.iterdir()) == []
