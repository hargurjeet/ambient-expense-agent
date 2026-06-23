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
import os
import json
import uuid
import logging
from fastapi import FastAPI, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.utils.service_factory import (
    create_session_service_from_options,
    create_memory_service_from_options,
    create_artifact_service_from_options,
)
from google.adk.runners import Runner
from google.genai import types
from google.adk.agents.run_config import RunConfig, StreamingMode

from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback
from expense_agent.agent import root_agent

logging.basicConfig(level=logging.INFO)
class StandardLogger:
    def log_struct(self, data, severity="INFO"):
        logging.info(f"[{severity}] {data}")
logger = StandardLogger()

setup_telemetry()
otel_to_cloud = False

allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
session_service_uri = None
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=otel_to_cloud,
)
app.title = "ambient-expense-agent"
app.description = "API for interacting with the Agent ambient-expense-agent"

session_service = create_session_service_from_options(
    base_dir=AGENT_DIR,
    session_service_uri=session_service_uri,
)
memory_service = create_memory_service_from_options(
    base_dir=AGENT_DIR,
)
artifact_service = create_artifact_service_from_options(
    base_dir=AGENT_DIR,
    artifact_service_uri=artifact_service_uri,
)


def normalize_subscription(subscription_path: str) -> str:
    if "/" in subscription_path:
        return subscription_path.split("/")[-1]
    return subscription_path


@app.post("/")
@app.post("/apps/expense_agent/trigger/pubsub")
async def pubsub_trigger(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"error": "Invalid JSON body"}

    user_id = "local-user"
    session_id = str(uuid.uuid4())
    payload_to_run = body

    if "subscription" in body and "message" in body:
        sub_path = body["subscription"]
        user_id = normalize_subscription(sub_path)
        message_id = body["message"].get("messageId") or body["message"].get("message_id")
        if message_id:
            session_id = message_id
        payload_to_run = body["message"]

    # Use module-level services instantiated above

    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        memory_service=memory_service,
        artifact_service=artifact_service,
        app_name="expense_agent",
        auto_create_session=True,
    )

    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=json.dumps(payload_to_run))]
    )

    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
        run_config=RunConfig(streaming_mode=StreamingMode.NONE),
    ):
        events.append(event)

    final_output = None
    for e in events:
        if e.output:
            final_output = e.output

    return {
        "status": "triggered",
        "user_id": user_id,
        "session_id": session_id,
        "final_output": final_output,
    }


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
