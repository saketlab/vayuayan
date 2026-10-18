"""All custom exceptions must derive from CPCBError."""

import pytest

from vayuayan import exceptions as exc


@pytest.mark.parametrize(
    "cls",
    [
        exc.NetworkError,
        exc.DataParsingError,
        exc.DataProcessingError,
        exc.CityNotFoundError,
        exc.StationNotFoundError,
        exc.InvalidDataError,
        exc.AuthenticationError,
        exc.RateLimitError,
        exc.ConfigurationError,
        exc.FileNotFoundError,
    ],
)
def test_inherits_base(cls):
    assert issubclass(cls, exc.CPCBError)
    with pytest.raises(exc.CPCBError):
        raise cls("boom")
