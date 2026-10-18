"""Tests for the shared HTTP helper: retries and the SSL fallback."""

import pytest
import requests

from vayuayan import http_client

from .fakes import FakeResponse


class _Session:
    """Answers each request with the next outcome, and records the calls."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append(kwargs.get("verify"))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(status=outcome)


@pytest.fixture(autouse=True)
def _fresh_hosts(monkeypatch):
    monkeypatch.setattr(http_client, "_INSECURE_HOSTS", set())
    monkeypatch.setattr(http_client.time, "sleep", lambda s: None)


def test_ssl_failure_is_resent_unverified_and_remembered_per_host():
    session = _Session(requests.exceptions.SSLError("bad cert"), 200, 200)
    for path in ("x", "y"):
        http_client.request(
            "get", f"https://a.example/{path}", session=session, ssl_fallback=True
        )
    assert session.calls == [True, False, False]


def test_ssl_failure_raises_by_default():
    session = _Session(requests.exceptions.SSLError("bad cert"))
    with pytest.raises(requests.exceptions.SSLError):
        http_client.request("get", "https://a.example", session=session)


def test_server_errors_are_retried_and_client_errors_are_not():
    session = _Session(503, requests.ConnectionError("reset"), 200)
    assert http_client.request("get", "https://a.example", session=session, retries=2)
    assert len(session.calls) == 3

    session = _Session(404, 200)
    with pytest.raises(requests.HTTPError):
        http_client.request("get", "https://a.example", session=session, retries=2)
    assert len(session.calls) == 1


class _Stream:
    """A streamed response that may fail part way."""

    def __init__(self, chunks, fail=False):
        self.headers = {"content-length": str(sum(map(len, chunks)))}
        self.chunks, self.fail = chunks, fail

    def iter_content(self, chunk_size):
        yield from self.chunks
        if self.fail:
            raise requests.ConnectionError("reset")


def test_stream_to_file_leaves_no_partial_file(tmp_path):
    path = tmp_path / "data.nc"
    assert http_client.stream_to_file(_Stream([b"ab", b"cd"]), path, "test") == 4
    assert path.read_bytes() == b"abcd"

    broken = tmp_path / "broken.nc"
    with pytest.raises(requests.ConnectionError):
        http_client.stream_to_file(_Stream([b"ab"], fail=True), broken, "test")
    assert list(tmp_path.iterdir()) == [path]
