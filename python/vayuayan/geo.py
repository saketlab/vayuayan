"""
India district boundaries (BharatViz LGD districts).
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Iterable, Optional, Union

from . import http_client

if TYPE_CHECKING:
    import geopandas as gpd

BHARATVIZ_DISTRICTS_URL = (
    "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson"
)

Names = Union[str, Iterable[str]]


@lru_cache(maxsize=1)
def _districts() -> gpd.GeoDataFrame:
    """The district polygons, downloaded once per session."""
    import geopandas as gpd

    # The server refuses urllib, which gpd.read_file(url) uses
    response = http_client.request("get", BHARATVIZ_DISTRICTS_URL, timeout=120)
    districts = gpd.read_file(io.BytesIO(response.content))
    districts["geometry"] = districts.geometry.make_valid()
    return districts.to_crs(4326)


def india_boundary(
    district: Optional[Names] = None, state: Optional[Names] = None
) -> Any:
    """Union of the district polygons of some districts, or of some states.

    Args:
        district: District name(s), matched to district_name.
        state: State name(s), matched to state_name. Used if district is None.

    Returns:
        A shapely geometry in EPSG:4326, such as the boundary to pass to
        PM2.5 statistics.

    Raises:
        ValueError: If neither is given, or no district matches.
    """
    if district is None and state is None:
        raise ValueError("Supply district or state")
    column, names = (
        ("district_name", district) if district is not None else ("state_name", state)
    )
    wanted = [names] if isinstance(names, str) else list(names or [])
    districts = _districts()
    selected = districts[districts[column].isin(wanted)]
    if selected.empty:
        raise ValueError("No BharatViz district matches the selection")
    return selected.geometry.make_valid().union_all()
