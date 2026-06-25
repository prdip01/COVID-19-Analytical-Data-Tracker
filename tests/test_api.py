"""
Integration tests for the COVID-19 Data Tracker Flask web application.

Verifies page renders, rate-limiting, database health check status,
and dynamic AJAX endpoint input validations.
"""

import json
from unittest.mock import patch
import pytest
from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app import app, cache, limiter
from database.models import Base
from database.connection import get_db, create_engine, sessionmaker, init_db


@pytest.fixture
def client():
    """Initializes a test Flask client and sets up clean testing configuration."""
    app.config["TESTING"] = True
    app.config["CACHE_TYPE"] = "SimpleCache"
    
    # Bypass rate limits by default for general testing, except when explicitly testing it
    app.config["RATELIMIT_ENABLED"] = False
    
    # Establish clean test database in memory
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    # Override app database engine
    with patch("app.get_db") as mock_get_db:
        # Mock connection pool
        Session = sessionmaker(bind=engine)
        
        # Helper context manager
        class MockSessionScope:
            def __init__(self):
                self.session = Session()
            def __enter__(self):
                return self.session
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type:
                    self.session.rollback()
                self.session.close()
                
        mock_get_db.side_effect = lambda: MockSessionScope()
        
        with app.test_client() as client:
            with app.app_context():
                cache.clear()
                yield client


def test_health_check_endpoint(client):
    """Verifies that the /health endpoint correctly reports database status and returns 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_home_page_render(client):
    """Verifies the dashboard home page resolves successfully and renders HTML structure."""
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.data.decode("utf-8")
    assert "<title>COVID-19 Global Data Tracker</title>" in html_content
    assert "Global Analysis Dashboard" in html_content


def test_api_cases_parameter_validation(client):
    """Tests that the dynamic charts endpoint correctly validates inputs and blocks SQL injection-like strings."""
    # 1. Missing countries list should fail
    res_err1 = client.get("/api/charts/cases?metric=cases")
    assert res_err1.status_code == 400
    assert "At least one country" in res_err1.json["error"]

    # 2. Invalid country names (suspicious injection character like single quote or semicolon)
    res_err2 = client.get("/api/charts/cases?countries=US;DROP TABLE daily_cases;--")
    assert res_err2.status_code == 400
    assert "Invalid country format" in res_err2.json["error"]

    # 3. Invalid date formats
    res_err3 = client.get("/api/charts/cases?countries=Canada&start_date=2020/02/22")
    assert res_err3.status_code == 400
    assert "Invalid start date format" in res_err3.json["error"]
    
    # 4. Invalid metric name
    res_err4 = client.get("/api/charts/cases?countries=Canada&metric=unsupported_metric_name")
    assert res_err4.status_code == 400
    assert "Invalid metric" in res_err4.json["error"]


@patch("app.run_pipeline")
def test_manual_refresh_trigger(mock_run, client):
    """Verifies that calling /api/refresh runs the ETL pipeline and clears the query caches."""
    mock_run.return_value = {
        "status": "success",
        "countries_inserted_or_updated": 5,
        "case_records_inserted_or_updated": 100,
        "vaccination_records_inserted_or_updated": 50
    }
    
    headers = {"X-API-Key": "test_admin_key"}
    response = client.post("/api/refresh", headers=headers)
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "success"
    assert data["case_records_inserted_or_updated"] == 100
    mock_run.assert_called_once()


def test_rate_limiting_on_refresh_route():
    """Verifies that the /api/refresh endpoint triggers a 429 Too Many Requests response if rate limit is exceeded."""
    # Create a fresh client with rate limiter enabled
    local_app = Flask(__name__)
    local_app.config["TESTING"] = True
    local_app.config["RATELIMIT_ENABLED"] = True
    
    local_limiter = Limiter(
        key_func=get_remote_address,
        app=local_app,
        default_limits=["1000 per hour"]
    )
    
    # Setup mock refresh route with a 1-per-minute limit for easy testing
    @local_app.route('/api/refresh', methods=['POST'])
    @local_limiter.limit("1 per minute")
    def test_refresh():
        return jsonify({"status": "ok"})
        
    with local_app.test_client() as local_client:
        # First request should succeed
        res1 = local_client.post("/api/refresh")
        assert res1.status_code == 200
        
        # Second request within the minute window should fail with 429
        res2 = local_client.post("/api/refresh")
        assert res2.status_code == 429
        assert "Too Many Requests" in res2.data.decode("utf-8")
