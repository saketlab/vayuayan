"""Fire detections read off ISRO MOSDAC's INSAT L2P fire preview images.

The image size picks the layout (LAYOUTS); a moved graticule raises ValueError.
A blob is a floor on the number of fire pixels, since nearby markers merge.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import shutil
import subprocess  # nosec B404: runs only the tesseract command, with a fixed argument list
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

import requests

from . import http_client
from .constants import get_cache_dir
from .utils import DateLike, _as_date

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from PIL import Image

MOSDAC_PREVIEW = "https://mosdac.gov.in/look/{sat}_IMG/preview/{y}/{dmon}/{sat}IMG_{dmon}{y}_{hm}_L2P_FIR_V01R00.jpg"
# minutes past each UTC hour
INSAT_MINUTES = {"3S": (0, 30), "3R": (15, 45), "3D": (0, 30)}
INSAT_COLUMNS = ["file", "layout", "time_utc", "header_count", "lon", "lat", "area_px"]
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
Anchors = Tuple[Tuple[float, float], Tuple[float, float]]


@dataclass(frozen=True)
class Layout:
    name: str
    x_lon: Anchors  # two (pixel x, longitude) anchors
    y_lat: Anchors  # two (pixel y, latitude) anchors
    # x0, y0, x1, y1 of the map (no header, logo or legend)
    map_box: Tuple[int, int, int, int]
    graticule: Tuple[int, int]  # x of a vertical and y of a horizontal graticule line
    light_lines: bool  # light grey lines on a dark map, or dark lines on a white one
    min_px: int  # smaller blobs are JPEG noise at marker edges (decoders differ there)


# (width, height) -> layout; 3S has ~12 px markers and a COUNT header, 3R ~2 x 5 px markers
LAYOUTS: Dict[Tuple[int, int], Layout] = {
    (2002, 2242): Layout("3S", ((168, 50), (1695, 100)), ((1912, 0), (485, 40)), (0, 245, 2002, 2242), (473, 1246), True, 10),
    (2000, 2434): Layout("3S-2024", ((501, 70), (1498, 90)), ((1829.5, 10), (762, 30)), (0, 150, 2000, 2300), (1000, 1313), True, 10),
    (1260, 1495): Layout("3R", ((20, 60), (1203.5, 100)), ((1381, 0), (89, 40)), (23, 92, 1200, 1378), (611, 777), False, 3),
}  # fmt: skip


def insat_fire_urls(
    start: DateLike, end: Optional[DateLike] = None, satellite: str = "3S"
) -> List[str]:
    """Preview image URLs for every slot from start to end (UTC days, inclusive)."""
    if satellite not in INSAT_MINUTES:
        raise ValueError(f"satellite must be one of {sorted(INSAT_MINUTES)}")
    first = _as_date(start)
    last = _as_date(end) if end is not None else first
    if last < first:
        raise ValueError("end is before start")
    urls = []
    day = first
    while day <= last:
        dmon = f"{day.day:02d}{MONTHS[day.month - 1]}"
        for h in range(24):
            for m in INSAT_MINUTES[satellite]:
                urls.append(
                    MOSDAC_PREVIEW.format(
                        sat=satellite, y=day.year, dmon=dmon, hm=f"{h:02d}{m:02d}"
                    )
                )
        day += dt.timedelta(days=1)
    return urls


def insat_fires(
    start: DateLike,
    end: Optional[DateLike] = None,
    satellite: str = "3S",
    bbox: Optional[Sequence[float]] = None,
) -> "pd.DataFrame":
    """Fires on every INSAT preview image from start to end (UTC days).

    Args:
        start: First day (UTC), as a date or "YYYY-MM-DD".
        end: Last day (UTC), inclusive; start if None.
        satellite: "3S" (INSAT-3DS, 2024 on), "3R" (INSAT-3DR) or "3D" (INSAT-3D).
        bbox: (west, south, east, north) to keep; all of the image if None.

    Returns:
        DataFrame with INSAT_COLUMNS, one row per fire blob: the image file
        name, its layout, time_utc (the image time), header_count (the
        product's own count, "3S" layout with tesseract only), lon, lat and
        area_px (the blob's size in pixels). Slots MOSDAC has no image for
        are skipped.
        JPEG libraries decode edge pixels differently, so area_px can
        differ by a few pixels and lon and lat by about 0.01 between systems.

    Raises:
        ValueError: If satellite is unknown, end is before start, or an
            image has an unknown layout.
        requests.RequestException: If a download fails other than with 404.
    """
    import pandas as pd

    frames = []
    for url in insat_fire_urls(start, end, satellite):
        path = _download(url)
        if path is not None:
            frames.append(parse_insat_fire_image(path))
    out = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=INSAT_COLUMNS)
    )
    if bbox is not None:
        w, s, e, n = bbox
        out = out[out["lon"].between(w, e) & out["lat"].between(s, n)].reset_index(
            drop=True
        )
    return out


def parse_insat_fire_image(
    path: Union[str, Path], read_count: bool = True
) -> "pd.DataFrame":
    """Fire blobs on one INSAT L2P fire preview image (INSAT_COLUMNS)."""
    import numpy as np
    import pandas as pd
    from PIL import Image

    path = Path(path)
    with Image.open(path) as im:
        name, blobs = parse_insat_fire_array(np.asarray(im.convert("RGB")))
        count = _header_count(im) if read_count and name == "3S" else None
    stamp = re.search(r"_(\d{2})([A-Z]{3})(\d{4})_(\d{2})(\d{2})_", path.name)
    when = (
        pd.Timestamp(
            int(stamp[3]),
            MONTHS.index(stamp[2]) + 1,
            int(stamp[1]),
            int(stamp[4]),
            int(stamp[5]),
            tz="UTC",
        )
        if stamp
        else pd.NaT
    )
    rows = [
        {
            "file": path.name,
            "layout": name,
            "time_utc": when,
            "header_count": count,
            **b,
        }
        for b in blobs
    ]
    return pd.DataFrame(rows, columns=INSAT_COLUMNS)


def parse_insat_fire_array(rgb: "np.ndarray") -> Tuple[str, List[Dict[str, float]]]:
    """Layout name and fire blobs (lon, lat, area_px) of an RGB image array (height x width x 3)."""
    import numpy as np

    h, w = rgb.shape[:2]
    if (w, h) not in LAYOUTS:
        raise ValueError(f"unknown INSAT preview layout {w} x {h}")
    lay = LAYOUTS[(w, h)]
    x0, y0, x1, y1 = lay.map_box
    gx, gy = lay.graticule
    # the calibration must still match the drawing
    for line in (rgb[y0:y1, gx], rgb[gy, x0:x1]):
        grey = np.ptp(line, axis=1) < 25
        grey &= line.mean(axis=1) > 150 if lay.light_lines else line.mean(axis=1) < 140
        if grey.mean() < 0.3:
            raise ValueError(
                f"{lay.name} graticule is not where expected; the layout has changed"
            )
    box = rgb[y0:y1, x0:x1].astype(np.int16)
    r, g, b = box[..., 0], box[..., 1], box[..., 2]
    red = np.zeros((h, w), dtype=bool)
    red[y0:y1, x0:x1] = (r - g > 40) & (r - b > 40) & (r > 120)
    blobs = []
    for ys, xs in _components(red):
        if len(xs) < lay.min_px:
            continue
        lon, lat = _to_lonlat(lay, float(np.mean(xs)), float(np.mean(ys)))
        blobs.append({"lon": round(lon, 3), "lat": round(lat, 3), "area_px": len(xs)})
    return lay.name, blobs


def _components(mask: "np.ndarray") -> List[Tuple[List[int], List[int]]]:
    """8-connected groups of True pixels, as (rows, cols), in row-major order of their first pixel."""
    import numpy as np

    todo = set(zip(*(v.tolist() for v in np.nonzero(mask))))
    groups = []
    for start in sorted(todo):
        if start not in todo:
            continue
        todo.discard(start)
        stack, ys, xs = [start], [], []
        while stack:
            y, x = stack.pop()
            ys.append(y)
            xs.append(x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nb = (y + dy, x + dx)
                    if nb in todo:
                        todo.discard(nb)
                        stack.append(nb)
        groups.append((ys, xs))
    return groups


def _merc(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _to_lonlat(lay: Layout, x: float, y: float) -> Tuple[float, float]:
    (xa, la), (xb, lb) = lay.x_lon
    (ya, aa), (yb, ab) = lay.y_lat
    lon = la + (x - xa) * (lb - la) / (xb - xa)
    m = _merc(aa) + (y - ya) * (_merc(ab) - _merc(aa)) / (yb - ya)
    return lon, math.degrees(2 * math.atan(math.exp(m)) - math.pi / 2)


def _header_count(im: "Image.Image") -> Optional[int]:
    """'COUNT:N POINTS' from a "3S" header, if the tesseract command is installed."""
    exe = shutil.which("tesseract")
    if exe is None:
        return None
    from PIL import ImageOps

    crop = ImageOps.invert(im.convert("L").crop((250, 95, 1600, 140)))
    crop = crop.resize((crop.width * 2, crop.height * 2))
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "header.png"
        crop.save(png)
        try:
            out = subprocess.run(
                [exe, str(png), "-", "--psm", "7"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )  # nosec B603
        except subprocess.TimeoutExpired:
            return None
    m = re.search(r"COUNT\s*:\s*([0-9OoIl]+)", out.stdout)
    return int(m[1].translate(str.maketrans("OoIl", "0011"))) if m else None


def _download(url: str) -> Optional[Path]:
    """Cached image path; None when MOSDAC has no image for the slot."""
    name = url.rsplit("/", 1)[1]
    path = get_cache_dir() / "insat" / name
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        body = http_client.request("get", url, retries=2, timeout=120).content
    except requests.HTTPError as e:
        if http_client.failure_reason(e) == "404":
            return None
        raise
    # MOSDAC answers some missing slots with an HTML page
    if not body.startswith(b"\xff\xd8"):
        return None
    with http_client.atomic_path(path) as part:
        part.write_bytes(body)
    return path
