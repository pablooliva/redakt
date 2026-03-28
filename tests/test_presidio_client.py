from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from redakt.services.presidio import PresidioClient


@pytest.fixture
def mock_http_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def presidio_client(mock_http_client):
    return PresidioClient(mock_http_client)


class TestPresidioClient:
    async def test_analyze_basic(self, presidio_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"entity_type": "PERSON", "start": 0, "end": 4, "score": 0.9}]
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        result = await presidio_client.analyze(
            text="John lives here",
            language="en",
            score_threshold=0.35,
        )
        assert len(result) == 1
        assert result[0]["entity_type"] == "PERSON"
        mock_http_client.post.assert_called_once()

    async def test_analyze_with_entities(self, presidio_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        await presidio_client.analyze(
            text="test",
            language="en",
            score_threshold=0.35,
            entities=["PERSON"],
        )
        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["entities"] == ["PERSON"]

    async def test_analyze_with_allow_list(self, presidio_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        await presidio_client.analyze(
            text="test",
            language="en",
            score_threshold=0.35,
            allow_list=["CompanyName"],
        )
        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["allow_list"] == ["CompanyName"]

    async def test_health_check_up(self, presidio_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.get.return_value = mock_response

        result = await presidio_client.check_health("analyzer")
        assert result is True

    async def test_health_check_down(self, presidio_client, mock_http_client):
        mock_http_client.get.side_effect = httpx.ConnectError("Connection refused")

        result = await presidio_client.check_health("analyzer")
        assert result is False
