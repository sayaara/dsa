# -*- coding: utf-8 -*-
"""
===================================
Analysis Integration Tests
===================================

Covers:
- API endpoint /analyze
- Name resolution to code
- Task queue submission
- Metadata persistence (original_query, selection_source)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.app import create_app
from src.services.task_queue import AnalysisTaskQueue, TaskStatus
from src.config import Config
import src.auth as auth

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def disable_auth():
    """Keep analysis integration tests independent from local auth env state."""
    auth._auth_enabled = None
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("src.auth.is_auth_enabled", return_value=False):
        yield
    auth._auth_enabled = None

@pytest.fixture
def mock_task_queue():
    with patch("api.v1.endpoints.analysis.get_task_queue") as mock_get:
        queue = MagicMock(spec=AnalysisTaskQueue)
        mock_get.return_value = queue
        yield queue

class TestAnalysisIntegration:
    """End-to-end integration tests for the analysis flow."""

    def test_trigger_analysis_flow_manual_name(self, client, mock_task_queue):
        """Test flow: User enters stock name -> resolved to code -> task submitted."""
        # Setup mock behavior
        mock_task_queue.submit_tasks_batch.return_value = (
            [MagicMock(task_id="test_task_123", stock_code="600519", analysis_phase="auto")],
            []
        )

        # Trigger analysis with a stock name
        response = client.post(
            "/api/v1/analysis/analyze",
            json={
                "stock_code": "贵州茅台",
                "async_mode": True,
                "original_query": "贵州茅台",
                "selection_source": "manual"
            }
        )

        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "test_task_123"
        assert data["status"] == "pending"
        # The single-stock 202 (TaskAccepted schema) carries no optional asset_type field; a legacy
        # MagicMock task must honour that contract even when asset_type is a MagicMock child object.
        assert "asset_type" not in data

        # Verify task queue received the correct resolved code and metadata.
        # Use call_args so this integration test stays focused on analysis flow
        # semantics even if the queue API gains orthogonal optional flags.
        mock_task_queue.submit_tasks_batch.assert_called_once()
        _, kwargs = mock_task_queue.submit_tasks_batch.call_args
        assert kwargs["stock_codes"] == ["600519"]
        assert kwargs["stock_name"] is None
        assert kwargs["original_query"] == "贵州茅台"
        assert kwargs["selection_source"] == "manual"
        assert kwargs["report_type"] == "detailed"
        assert kwargs["analysis_phase"] == "auto"
        assert kwargs["force_refresh"] is False
        assert kwargs["notify"] is True


    def test_trigger_analysis_dos_protection(self, client):
        """Test that excessive stock codes are rejected."""
        too_many_codes = [f"{i:06d}" for i in range(101)]
        response = client.post(
            "/api/v1/analysis/analyze",
            json={
                "stock_codes": too_many_codes,
                "async_mode": True
            }
        )

        assert response.status_code == 400
        assert "at most" in response.json()["message"]


