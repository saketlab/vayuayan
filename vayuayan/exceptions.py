"""
Custom exceptions for the CPCB data fetching package.

This module defines exception classes used throughout the vayuayan package
to provide specific error handling for different types of failures.
"""


class CPCBError(Exception):
    """Base exception for all CPCB related errors.

    This is the base class for all custom exceptions in the vayuayan package.
    All other exceptions inherit from this class.
    """

    pass


class NetworkError(CPCBError):
    """Raised when network requests fail.

    This exception is raised when HTTP requests to CPCB services fail due to
    network issues, timeouts, or server errors.
    """

    pass


class DataParsingError(CPCBError):
    """Raised when data parsing fails.

    This exception is raised when received data cannot be parsed or processed,
    such as malformed JSON, corrupt Excel files, or unexpected data formats.
    """

    pass


class DataProcessingError(CPCBError):
    """Raised when data processing operations fail.

    This exception is raised when operations like base64 decoding, data
    transformation, or statistical calculations fail.
    """

    pass


class CityNotFoundError(CPCBError):
    """Raised when a city is not found in the CPCB database.

    This exception is raised when a requested city or location is not
    available in the CPCB monitoring network.
    """

    pass


class StationNotFoundError(CPCBError):
    """Raised when a monitoring station is not found.

    This exception is raised when a requested station ID or station name
    is not available in the CPCB monitoring network.
    """

    pass


class InvalidDataError(CPCBError):
    """Raised when received data is invalid or corrupted.

    This exception is raised when data validation fails, such as missing
    required fields, invalid coordinates, or data outside expected ranges.
    """

    pass


class AuthenticationError(CPCBError):
    """Raised when authentication with CPCB services fails.

    This exception is raised when API authentication fails or access
    is denied to CPCB services.
    """

    pass


class RateLimitError(CPCBError):
    """Raised when API rate limits are exceeded.

    This exception is raised when too many requests are made to CPCB
    services in a short period of time.
    """

    pass


class FileNotFoundError(CPCBError):
    """Raised when a required file is not found.

    This exception is raised when attempting to access files (NetCDF, GeoJSON)
    that don't exist at the specified paths.
    """

    pass


class ConfigurationError(CPCBError):
    """Raised when configuration is invalid or missing.

    This exception is raised when required configuration parameters
    are missing or have invalid values.
    """

    pass
