"""Fakes that several test files share."""

import base64
import json
from typing import Any, Dict, List, NamedTuple, Tuple

import requests


class Call(NamedTuple):
    """One request that reached the fake network."""

    method: str
    url: str
    kwargs: Dict[str, Any]


class FakeNetwork:
    """Stands in for the requests library, under the real http_client.

    Each route answers with its outcomes in turn and then repeats the last one.
    An outcome that is an exception is raised. A URL with no route fails the
    test, so a changed CPCB route cannot pass unnoticed.
    """

    def __init__(self):
        self.calls: List[Call] = []
        self.sleeps: List[float] = []
        self._routes: Dict[Tuple[str, str], List[Any]] = {}

    def on(self, method, url, *outcomes):
        """Answer requests for this method and URL (without its query string)."""
        self._routes[(method, url)] = list(outcomes)

    def __call__(self, method, url, **kwargs):
        self.calls.append(Call(method.lower(), url, kwargs))
        outcomes = self._routes.get((method.lower(), url.split("?")[0]))
        if outcomes is None:
            raise AssertionError(f"unexpected request: {method} {url}")
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def urls(self):
        return [call.url for call in self.calls]


def http_response(body=b"", status=200, json_data=None, headers=None):
    """A real requests.Response, so json() and raise_for_status() are the real ones."""
    response = requests.Response()
    response.status_code = status
    response._content = (
        json.dumps(json_data).encode() if json_data is not None else body
    )
    response._content_consumed = True
    response.headers.update(headers or {})
    return response


def b64_body(data):
    """The base64 JSON body that the old CPCB endpoints send."""
    return base64.b64encode(json.dumps(data).encode())


def b64_decode(text):
    """The object in a base64 JSON request body."""
    return json.loads(base64.b64decode(text))


class FakeResponse:
    """A requests.Response with a status, a body and JSON data."""

    def __init__(self, content=b"", json_data=None, status=200):
        self.content = content
        self.status_code = status
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


def write_pm25_netcdf(
    client, value=40.0, step=0.5, nan_inside=None, year=2020, month=1
):
    """Write the client's NetCDF for a month, one value over 20-30 N, 70-85 E.

    nan_inside is (south, west, north, east); that band of latitudes is NaN.
    """
    import numpy as np
    import xarray as xr

    lat = np.arange(30.0, 20.0, -step)
    lon = np.arange(70.0, 85.0, step)
    data = np.full((lat.size, lon.size), float(value))
    if nan_inside is not None:
        south, _, north, _ = nan_inside
        data[(lat >= south) & (lat <= north), :] = np.nan
    ds = xr.Dataset({"PM25": (("lat", "lon"), data)}, coords={"lat": lat, "lon": lon})
    ds.to_netcdf(client.get_netcdf_path(year, month))


def raise_connection_error(*args, **kwargs):
    """A stand-in for a request to a server that is down."""
    raise requests.ConnectionError("CPCB is down")
