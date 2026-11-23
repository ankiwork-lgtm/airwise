"""Health check route."""

from __future__ import annotations

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Register the health route on ``app``."""

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Report that the service is up."""
        return {"status": "ok"}
