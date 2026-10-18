"""
Exception classes of the vayuayan package.

Each class identifies one type of failure, so that callers can catch it.
"""


class CPCBError(Exception):
    """Base class for all vayuayan exceptions.

    All other exceptions in the vayuayan package inherit from this class.
    """


class NetworkError(CPCBError):
    """Error when a network request fails.

    A network problem, a timeout, or a server error can cause this error.
    """


class DataParsingError(CPCBError):
    """Error when the client cannot parse the data.

    Malformed JSON, a corrupt Excel file, or an unknown data format can cause
    this error.
    """


class DataProcessingError(CPCBError):
    """Error when a data operation fails.

    Examples are a failed base64 decode, a failed data transformation, and a
    failed statistical calculation.
    """


class CityNotFoundError(CPCBError):
    """Error when the CPCB database does not have a city.

    The CPCB monitoring network does not have the requested city or location.
    """


class StationNotFoundError(CPCBError):
    """Error when the client cannot find a monitoring station.

    The CPCB monitoring network does not have the requested station ID or
    station name.
    """


class DataNotFoundError(CPCBError):
    """Error when CPCB answers, but has no data for the request.

    For example, there is no file for the station and year. A network failure
    raises NetworkError instead, so callers can tell the two apart.
    """


class InvalidDataError(CPCBError):
    """Error when the received data is not valid.

    Examples are a missing necessary field, invalid coordinates, and data
    outside the expected range.
    """


class AuthenticationError(CPCBError):
    """Error when the authentication with CPCB services fails.

    The API authentication failed, or CPCB refused the access.
    """


class RateLimitError(CPCBError):
    """Error when the client goes above the API rate limit.

    The client sent too many requests to CPCB services in a short time.
    """


class FileNotFoundError(CPCBError):
    """Error when a necessary file does not exist.

    A NetCDF file or a GeoJSON file is not at the given path.
    """


class ConfigurationError(CPCBError):
    """Error when the configuration is missing or not valid.

    A necessary configuration parameter is missing or has an invalid value.
    """
