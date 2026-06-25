from unittest.mock import patch
import pytest
from etl.pipeline import ETLLockError

def test_api_refresh_missing_key(test_client):
    """Verify that accessing /api/refresh without X-API-Key returns 403 Forbidden."""
    response = test_client.post("/api/refresh")
    assert response.status_code == 403
    assert "Invalid or missing X-API-Key" in response.json["error"]

def test_api_refresh_invalid_key(test_client):
    """Verify that accessing /api/refresh with an invalid X-API-Key returns 403 Forbidden."""
    headers = {"X-API-Key": "wrong_key"}
    response = test_client.post("/api/refresh", headers=headers)
    assert response.status_code == 403
    assert "Invalid or missing X-API-Key" in response.json["error"]

@patch("app.run_pipeline")
def test_api_refresh_success(mock_run, test_client):
    """Verify that accessing /api/refresh with a valid X-API-Key returns 200 OK and runs the pipeline."""
    mock_run.return_value = {"status": "success", "countries_inserted_or_updated": 1}
    headers = {"X-API-Key": "test_admin_key"}
    response = test_client.post("/api/refresh", headers=headers)
    assert response.status_code == 200
    assert response.json["status"] == "success"
    mock_run.assert_called_once()

def test_csrf_protection_enforcement(test_app, test_client):
    """Verify that CSRF protection is active on non-exempt routes and blocks requests without token."""
    # Temporarily set TESTING to False to enable CSRF check in Flask-WTF
    test_app.config["TESTING"] = False
    try:
        # Making a POST request without a CSRF token should return 400 Bad Request
        response = test_client.post("/api/test-csrf-target")
        assert response.status_code == 400
    finally:
        test_app.config["TESTING"] = True

    # Making a POST request to the CSRF-exempt /api/refresh route should NOT trigger 400 CSRF error
    # It should pass CSRF and fail on API key authentication instead (403)
    response_refresh = test_client.post("/api/refresh")
    assert response_refresh.status_code == 403
    assert "Invalid or missing X-API-Key" in response_refresh.json["error"]

@patch("app.run_pipeline")
def test_api_refresh_concurrency_lock(mock_run, test_client):
    """Verify that /api/refresh returns 423 Locked if the ETL lock is already held."""
    mock_run.side_effect = ETLLockError("ETL pipeline is already running.")
    headers = {"X-API-Key": "test_admin_key"}
    response = test_client.post("/api/refresh", headers=headers)
    assert response.status_code == 423
    assert "already running" in response.json["error"]
