"""Health check route."""

from __future__ import annotations

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Register the health route on ``app``."""

    @app.get(
        "/api/health",
        response_model=dict[str, str],
        summary="Service health check",
        description="Verify service availability and responsiveness.",
        tags=["Health"],
        responses={200: {"description": "Service is healthy and accepting requests."}},
    )
    async def health() -> dict[str, str]:
        """Report that the service is up."""
        return {"status": "ok"}
