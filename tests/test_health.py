from unittest.mock import AsyncMock, patch


class TestHealthEndpoint:
    def test_health_all_up(self, client, mock_presidio_health):
        mock_presidio_health.return_value = True
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["presidio_analyzer"] == "up"
        assert data["presidio_anonymizer"] == "up"

    def test_health_all_down(self, client):
        with patch(
            "redakt.services.presidio.PresidioClient.check_health",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["presidio_analyzer"] == "down"
        assert data["presidio_anonymizer"] == "down"

    def test_health_analyzer_down_anonymizer_up(self, client):
        async def selective_health(service="analyzer"):
            return service != "analyzer"

        with patch(
            "redakt.services.presidio.PresidioClient.check_health",
            new_callable=AsyncMock,
            side_effect=selective_health,
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["presidio_analyzer"] == "down"
        assert data["presidio_anonymizer"] == "up"

    def test_health_analyzer_up_anonymizer_down(self, client):
        async def selective_health(service="analyzer"):
            return service == "analyzer"

        with patch(
            "redakt.services.presidio.PresidioClient.check_health",
            new_callable=AsyncMock,
            side_effect=selective_health,
        ):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["presidio_analyzer"] == "up"
        assert data["presidio_anonymizer"] == "down"

    def test_liveness(self, client):
        resp = client.get("/api/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
