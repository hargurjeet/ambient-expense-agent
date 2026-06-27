# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import google.auth
from google.auth.exceptions import DefaultCredentialsError
from unittest.mock import MagicMock

# 1. Raise DefaultCredentialsError to force agent.py to use Developer API (GEMINI_API_KEY)
def raise_default_credentials_error(*args, **kwargs):
    raise DefaultCredentialsError("Mock DefaultCredentialsError")

google.auth.default = raise_default_credentials_error

# Import agent.py first to trigger the try-except block
import expense_agent.agent

# 2. Mock google.auth.default to return mock credentials for AgentEngineApp initialization
mock_creds = MagicMock(spec=google.auth.credentials.Credentials)
google.auth.default = lambda *args, **kwargs: (mock_creds, "ambient-expense-agent-500708")

# 3. Mock google.cloud.logging.Client to prevent real logging API calls during tests
import google.cloud.logging
mock_logging_client = MagicMock()
google.cloud.logging.Client = lambda *args, **kwargs: mock_logging_client

# Set required environment variables
os.environ["GOOGLE_CLOUD_PROJECT"] = "ambient-expense-agent-500708"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import pytest
from google.adk.events.event import Event

from expense_agent.agent_runtime_app import AgentEngineApp


@pytest.fixture
def agent_app(monkeypatch: pytest.MonkeyPatch) -> AgentEngineApp:
    """Fixture to create and set up AgentEngineApp instance"""
    # Set integration test flag to mock external services
    monkeypatch.setenv("INTEGRATION_TEST", "TRUE")

    from expense_agent.agent_runtime_app import agent_runtime

    agent_runtime.set_up()
    return agent_runtime


@pytest.mark.asyncio
async def test_agent_stream_query(agent_app: AgentEngineApp) -> None:
    """
    Integration test for the agent stream query functionality.
    Tests that the agent returns valid streaming responses.
    """
    # Create message and events for the async_stream_query
    import json
    payload = {
        "data": {
            "amount": 45.00,
            "submitter": "Alice",
            "category": "Office Supplies",
            "description": "Premium notebooks and pens",
            "date": "2026-06-23"
        }
    }
    message = json.dumps(payload)
    events = []
    async for event in agent_app.async_stream_query(message=message, user_id="test"):
        events.append(event)
    assert len(events) > 0, "Expected at least one chunk in response"

    # Check for valid content in the response
    has_text_content = False
    for event in events:
        validated_event = Event.model_validate(event)
        content = validated_event.content
        if (
            content is not None
            and content.parts
            and any(part.text for part in content.parts)
        ):
            has_text_content = True
            break

    assert has_text_content, "Expected at least one event with text content"


def test_agent_feedback(agent_app: AgentEngineApp) -> None:
    """
    Integration test for the agent feedback functionality.
    Tests that feedback can be registered successfully.
    """
    feedback_data = {
        "score": 5,
        "text": "Great response!",
        "user_id": "test-user-456",
        "session_id": "test-session-456",
    }

    # Should not raise any exceptions
    agent_app.register_feedback(feedback_data)

    # Test invalid feedback
    with pytest.raises(ValueError):
        invalid_feedback = {
            "score": "invalid",  # Score must be numeric
            "text": "Bad feedback",
            "user_id": "test-user-789",
            "session_id": "test-session-789",
        }
        agent_app.register_feedback(invalid_feedback)

    logging.info("All assertions passed for agent feedback test")
