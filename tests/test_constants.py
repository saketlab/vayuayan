"""Tests for config-path helpers and AQI threshold table."""

from pathlib import Path

from vayuayan.constants import (
    AQI_CATEGORIES,
    get_config_dir,
    get_gee_project_file,
)


def test_get_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    d = get_config_dir()
    assert d == tmp_path / "vayuayan"
    assert d.is_dir()  # the call makes the directory


def test_get_gee_project_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    f = get_gee_project_file()
    assert f == tmp_path / "vayuayan" / "gee_project"
    assert isinstance(f, Path)


def test_aqi_categories_contiguous():
    # The bands must be in order, and they must not overlap.
    bands = list(AQI_CATEGORIES.values())
    for lo, hi in zip(bands, bands[1:]):
        assert lo["max"] + 1 == hi["min"]


def test_user_dirs_follow_the_platform(tmp_path, monkeypatch):
    from vayuayan.constants import get_cache_dir

    monkeypatch.delenv("VAYUAYAN_CACHE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert get_cache_dir() == tmp_path / "AppData" / "Local" / "vayuayan" / "cache"
    assert get_config_dir() == tmp_path / "AppData" / "Local" / "vayuayan"

    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert get_cache_dir() == tmp_path / ".cache" / "vayuayan"
    monkeypatch.setenv("VAYUAYAN_CACHE_DIR", str(tmp_path / "mine"))
    assert get_cache_dir() == tmp_path / "mine"
