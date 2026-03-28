import httpx
from fastapi import Request

from redakt.config import settings


class PresidioClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client
        self._analyzer_url = settings.presidio_analyzer_url
        self._anonymizer_url = settings.presidio_anonymizer_url

    async def analyze(
        self,
        text: str,
        language: str,
        score_threshold: float,
        entities: list[str] | None = None,
        allow_list: list[str] | None = None,
    ) -> list[dict]:
        payload: dict = {
            "text": text,
            "language": language,
            "score_threshold": score_threshold,
        }
        if entities:
            payload["entities"] = entities
        if allow_list:
            payload["allow_list"] = allow_list

        response = await self._client.post(
            f"{self._analyzer_url}/analyze",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def check_health(self, service: str = "analyzer") -> bool:
        url = self._analyzer_url if service == "analyzer" else self._anonymizer_url
        try:
            response = await self._client.get(f"{url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def get_presidio_client(request: Request) -> PresidioClient:
    return PresidioClient(request.app.state.http_client)
