"""Fakes that several test files share."""

import requests


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


def raise_connection_error(*args, **kwargs):
    """A stand-in for a request to a server that is down."""
    raise requests.ConnectionError("CPCB is down")
