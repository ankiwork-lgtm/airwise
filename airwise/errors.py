"""Application error hierarchy. Each error carries an HTTP status, code, and field names."""

from __future__ import annotations


class AppError(Exception):
    """Base error: carries the HTTP status, machine code, message, field names and headers."""

    status: int = 500
    code: str = "server_error"
    message: str = "Internal server error."

    def __init__(
        self,
        message: str | None = None,
        fields: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Override the class default message, and attach field names and response headers."""
        self.message = message if message is not None else type(self).message
        self.fields: list[str] = list(fields or [])
        self.headers: dict[str, str] = dict(headers or {})
        super().__init__(self.message)


class ValidationFailure(AppError):
    """The request failed validation (HTTP 422)."""

    status = 422
    code = "validation_error"
    message = "Invalid request."


class InvalidInput(ValidationFailure):
    """A single named field is invalid."""

    def __init__(self, field: str, message: str | None = None) -> None:
        """Name the invalid ``field``; the message defaults to a generic one."""
        super().__init__(message or f"Invalid input: {field}.", [field])


class InvalidCity(ValidationFailure):
    """The city name is empty or too long."""

    message = "City must be 1 to 100 characters."

    def __init__(self, message: str | None = None) -> None:
        """Report the ``city`` field as invalid."""
        super().__init__(message, ["city"])


class PayloadTooLarge(AppError):
    """The request body exceeds the size limit (HTTP 413)."""

    status = 413
    code = "payload_too_large"
    message = "Request body is too large."


class RateLimited(AppError):
    """The client sent too many requests (HTTP 429, with a Retry-After header)."""

    status = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        """Record the number of seconds after which the client may retry."""
        super().__init__(message, headers={"Retry-After": str(retry_after)})
        self.retry_after = retry_after


class CityNotFound(AppError):
    """Geocoding found no match for the city (HTTP 404)."""

    status = 404
    code = "city_not_found"
    message = "City not found."


class LookupUnavailable(AppError):
    """An upstream location or air quality lookup failed (HTTP 502)."""

    status = 502
    code = "lookup_unavailable"
    message = "Location lookup is unavailable. Please try again later."
