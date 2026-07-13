import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

logger = logging.getLogger(__name__)


def _mock_client():
    client = MagicMock()
    client.admin_delete_agent.return_value = {
        "agent_id": "test-id-123",
        "name": "to-delete",
        "deleted": True,
    }
    return client


def test_admin_delete_agent_calls_hub():
    client = _mock_client()
    result = client.admin_delete_agent("test-id-123")
    assert result["deleted"] is True
    assert result["name"] == "to-delete"
    client.admin_delete_agent.assert_called_once_with("test-id-123")


def test_admin_delete_agent_raises_on_error():
    client = MagicMock()
    client.admin_delete_agent.side_effect = Exception("404 Not Found")
    with pytest.raises(Exception, match="404"):
        client.admin_delete_agent("nonexistent-id")
