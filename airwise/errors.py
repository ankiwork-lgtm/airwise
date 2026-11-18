"""Application error hierarchy. Each error carries an HTTP status, code, and field names."""
from __future__ import annotations


class AppError(Exception):
    status: int = 500
    code: str = "server_error"
    message: str = "Internal server error."

    def __init__(
        self,
        message: str | None = None,
        fields: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message if message is not None else type(self).message
        self.fields: list[str] = list(fields or [])
        self.headers: dict[str, str] = dict(headers or {})
        super().__init__(self.message)


class ValidationFailure(AppError):
    status = 422
    code = "validation_error"
    message = "Invalid request."


class InvalidInput(ValidationFailure):
    def __init__(self, field: str, message: str | None = None) -> None:
        super().__init__(message or f"Invalid input: {field}.", [field])


class InvalidCity(ValidationFailure):
    message = "City must be 1 to 100 characters."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, ["city"])


class PayloadTooLarge(AppError):
    status = 413
    code = "payload_too_large"
    message = "Request body is too large."


class RateLimited(AppError):
    status = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)})
        self.retry_after = retry_after


class CityNotFound(AppError):
    status = 404
    code = "city_not_found"
    message = "City not found."


class LookupUnavailable(AppError):
    status = 502
    code = "lookup_unavailable"
    message = "Location lookup is unavailable. Please try again later."
