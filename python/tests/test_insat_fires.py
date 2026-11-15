"""INSAT fire previews: URLs, layout checks, blob positions and the download path (offline)."""

from typing import List

import numpy as np
import pytest
import requests

from vayuayan import insat as ins

from .fakes import FakeResponse


def fake_3s(fires: List[tuple]) -> np.ndarray:
    """A "3S" layout image: dark map, light graticule, 12 px red squares at (lon, lat)."""
    lay = ins.LAYOUTS[(2002, 2242)]
    img = np.full((2242, 2002, 3), 30, dtype=np.uint8)
    gx, gy = lay.graticule
    img[:, gx] = 200
    img[gy, :] = 200
    (xa, la), (xb, lb) = lay.x_lon
    (ya, aa), (yb, ab) = lay.y_lat
    for lon, lat in fires:
        x = xa + (lon - la) * (xb - xa) / (lb - la)
        m = ins._merc(lat)
        y = ya + (m - ins._merc(aa)) * (yb - ya) / (ins._merc(ab) - ins._merc(aa))
        img[round(y) - 6 : round(y) + 6, round(x) - 6 : round(x) + 6] = (230, 20, 20)
    return img


def test_blobs_land_back_on_their_coordinates():
    name, blobs = ins.parse_insat_fire_array(fake_3s([(75.8, 30.9), (76.4, 30.3)]))
    assert name == "3S"
    got = sorted((b["lon"], b["lat"]) for b in blobs)
    assert np.allclose(got, [(75.8, 30.9), (76.4, 30.3)], atol=0.04)
    assert [b["area_px"] for b in blobs] == [144, 144]


def test_a_moved_graticule_or_new_size_is_an_error():
    img = fake_3s([])
    img[:, 473] = 30  # the vertical line is gone
    with pytest.raises(ValueError, match="graticule"):
        ins.parse_insat_fire_array(img)
    with pytest.raises(ValueError, match="layout"):
        ins.parse_insat_fire_array(np.zeros((100, 100, 3), dtype=np.uint8))


def test_urls_follow_each_satellites_minutes():
    s = ins.insat_fire_urls("2026-11-01", satellite="3S")
    assert len(s) == 48
    assert s[35] == (
        "https://mosdac.gov.in/look/3S_IMG/preview/2026/01NOV/"
        "3SIMG_01NOV2026_1730_L2P_FIR_V01R00.jpg"
    )
    assert ins.insat_fire_urls("2025-10-05", satellite="3R")[0].endswith(
        "_0015_L2P_FIR_V01R00.jpg"
    )
    assert ins.insat_fire_urls("2016-11-01", satellite="3D")[1].endswith(
        "_0030_L2P_FIR_V01R00.jpg"
    )
    with pytest.raises(ValueError):
        ins.insat_fire_urls("2026-11-01", satellite="GOES")


def test_insat_fires_parses_cached_images_and_skips_missing_slots(
    monkeypatch, tmp_path
):
    PIL = pytest.importorskip("PIL.Image")
    path = tmp_path / "3SIMG_01NOV2026_1130_L2P_FIR_V01R00.png"
    PIL.fromarray(fake_3s([(75.8, 30.9), (88.0, 22.5)])).save(path)
    monkeypatch.setattr(ins, "_download", lambda url: path if "_1130_" in url else None)
    got = ins.insat_fires("2026-11-01", bbox=(73.5, 27.6, 77.8, 32.6))
    assert list(got.columns) == ins.INSAT_COLUMNS
    assert len(got) == 1  # the Bengal fire is outside the box
    assert got["time_utc"].iloc[0].isoformat() == "2026-11-01T11:30:00+00:00"


def test_download_returns_none_for_404_and_html(monkeypatch):
    def fake(method, url, **kw):
        if "MISSING" in url:
            raise requests.HTTPError(response=FakeResponse(status=404))
        return FakeResponse(content=b"<html>no image</html>")

    monkeypatch.setattr(ins.http_client, "request", fake)
    assert ins._download("https://x/MISSING.jpg") is None
    assert ins._download("https://x/page.jpg") is None
