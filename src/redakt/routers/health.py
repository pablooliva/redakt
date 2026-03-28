from fastapi import APIRouter, Depends

from redakt.models.common import HealthResponse
from redakt.services.presidio import PresidioClient, get_presidio_client

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health/live")
async def liveness() -> dict:
    """Liveness probe — always returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/health", response_model=HealthResponse)
async def health_check(
    presidio: PresidioClient = Depends(get_presidio_client),
) -> HealthResponse:
    """Readiness probe — checks Presidio connectivity."""
    analyzer_healthy = await presidio.check_health("analyzer")
    anonymizer_healthy = await presidio.check_health("anonymizer")

    analyzer_status = "up" if analyzer_healthy else "down"
    anonymizer_status = "up" if anonymizer_healthy else "down"

    overall = "healthy" if analyzer_healthy and anonymizer_healthy else "degraded"

    return HealthResponse(
        status=overall,
        presidio_analyzer=analyzer_status,
        presidio_anonymizer=anonymizer_status,
    )
