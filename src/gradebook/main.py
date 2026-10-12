"""Entry point for the Gradebook Report Service.

This module defines the FastAPI application object. Every endpoint
in the API contract will attach to this one object — either right
here, or via routers we import from sibling modules as the project
grows. Keeping a single canonical "app" is what lets uvicorn find
it with a short instruction like `gradebook.main:app`.
"""

from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(
    title="Gradebook Report Service",
    version="0.1.0",
    description="Turn several teachers' spreadsheets into one class report.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Returns a small JSON document telling the caller the process is
    up and answering. A human can hit this in a browser; a Docker
    HEALTHCHECK, a load balancer, or a monitoring system can hit it
    every few seconds. The timestamp is what makes it useful: if
    the time stops advancing, the process is stuck, even if it has
    not yet crashed.
    """
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }