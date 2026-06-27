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


from fastapi.responses import HTMLResponse

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ambient Expense Approval Agent</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --container-bg: rgba(17, 24, 39, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --primary-color: #3b82f6;
            --primary-hover: #2563eb;
            --text-color: #e2e8f0;
            --text-muted: #94a3b8;
            --bubble-user: #2563eb;
            --bubble-agent: #1e293b;
            --success-color: #10b981;
            --error-color: #ef4444;
            --warning-color: #f59e0b;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.1) 0px, transparent 50%);
            background-attachment: fixed;
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .app-container {
            width: 100%;
            max-width: 900px;
            height: 85vh;
            background: var(--container-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        }
        .header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            background-color: var(--success-color);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--success-color);
        }
        .header h1 {
            font-size: 1.25rem;
            font-weight: 600;
        }
        .header p {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-top: 2px;
        }
        .reset-btn {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 8px 16px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.2s ease;
        }
        .reset-btn:hover {
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.15);
        }
        .chat-area {
            flex: 1;
            padding: 24px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .message {
            max-width: 75%;
            padding: 14px 18px;
            border-radius: 18px;
            font-size: 0.95rem;
            line-height: 1.5;
            white-space: pre-wrap;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message.user {
            background-color: var(--bubble-user);
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        .message.agent {
            background-color: var(--bubble-agent);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            border: 1px solid var(--border-color);
        }
        .message.info {
            background: rgba(245, 158, 11, 0.1);
            border: 1px solid rgba(245, 158, 11, 0.2);
            color: #fef08a;
            align-self: center;
            max-width: 90%;
            border-radius: 14px;
            text-align: center;
        }
        .hil-actions {
            display: flex;
            gap: 12px;
            margin-top: 12px;
            justify-content: center;
        }
        .hil-btn {
            padding: 10px 24px;
            border-radius: 12px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .hil-btn.approve {
            background-color: var(--success-color);
            color: #fff;
        }
        .hil-btn.approve:hover {
            background-color: #059669;
            transform: translateY(-2px);
        }
        .hil-btn.reject {
            background-color: var(--error-color);
            color: #fff;
        }
        .hil-btn.reject:hover {
            background-color: #dc2626;
            transform: translateY(-2px);
        }
        .input-area {
            padding: 20px 24px;
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 12px;
            background: rgba(10, 15, 30, 0.5);
        }
        .text-input {
            flex: 1;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 14px 18px;
            color: var(--text-color);
            font-family: inherit;
            font-size: 0.95rem;
            outline: none;
            transition: all 0.2s ease;
        }
        .text-input:focus {
            border-color: var(--primary-color);
            background: rgba(255, 255, 255, 0.05);
            box-shadow: 0 0 10px rgba(59, 130, 246, 0.2);
        }
        .send-btn {
            background-color: var(--primary-color);
            color: #fff;
            border: none;
            border-radius: 16px;
            padding: 0 24px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .send-btn:hover {
            background-color: var(--primary-hover);
        }
        .send-btn:disabled {
            background-color: #1e293b;
            color: var(--text-muted);
            cursor: not-allowed;
        }
        .typing-indicator {
            align-self: flex-start;
            background-color: var(--bubble-agent);
            padding: 14px 18px;
            border-radius: 18px;
            border-bottom-left-radius: 4px;
            border: 1px solid var(--border-color);
            display: none;
            gap: 5px;
        }
        .typing-dot {
            width: 8px;
            height: 8px;
            background-color: var(--text-muted);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out both;
        }
        .typing-dot:nth-child(1) { animation-delay: -0.32s; }
        .typing-dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1.0); }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="header">
            <div class="header-title">
                <div class="status-dot"></div>
                <div>
                    <h1>Ambient Expense Approval Agent</h1>
                    <p>ADK 2.0 • Security checkpoint & escrow routing</p>
                </div>
            </div>
            <button class="reset-btn" onclick="resetSession()">Reset Session</button>
        </div>
        <div class="chat-area" id="chatArea">
            <div class="message agent">Welcome! I am the Ambient Expense Approval Agent.
You can submit a claim in JSON/PubSub format, or just type standard requests like:
• <i>"I want to submit an expense for lunch: $85"</i>
• <i>"Hotel stay for $250"</i> (triggers manual approval)</div>
        </div>
        <div class="typing-indicator" id="typingIndicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
        <div class="input-area">
            <input type="text" class="text-input" id="messageInput" placeholder="Type a message..." onkeydown="handleKeydown(event)">
            <button class="send-btn" id="sendBtn" onclick="sendMessage()">Send</button>
        </div>
    </div>

    <script>
        const chatArea = document.getElementById('chatArea');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const typingIndicator = document.getElementById('typingIndicator');

        let userId = localStorage.getItem('userId') || 'user_' + Math.random().toString(36).substring(2, 10);
        let sessionId = localStorage.getItem('sessionId') || 'session_' + Math.random().toString(36).substring(2, 18);

        localStorage.setItem('userId', userId);
        localStorage.setItem('sessionId', sessionId);

        function handleKeydown(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }

        function resetSession() {
            sessionId = 'session_' + Math.random().toString(36).substring(2, 18);
            localStorage.setItem('sessionId', sessionId);
            chatArea.innerHTML = `
                <div class="message agent">Session reset! Welcome! I am the Ambient Expense Approval Agent.
You can submit a claim in JSON/PubSub format, or just type standard requests like:
• <i>"I want to submit an expense for lunch: $85"</i>
• <i>"Hotel stay for $250"</i> (triggers manual approval)</div>
            `;
        }

        function appendMessage(text, isUser, type = '') {
            const msgDiv = document.createElement('div');
            msgDiv.className = 'message ' + (isUser ? 'user' : 'agent') + (type ? ' ' + type : '');
            msgDiv.innerHTML = text;
            chatArea.appendChild(msgDiv);
            chatArea.scrollTop = chatArea.scrollHeight;
        }

        async function sendMessage() {
            const message = messageInput.value.trim();
            if (!message) return;

            appendMessage(message, true);
            messageInput.value = '';
            messageInput.disabled = true;
            sendBtn.disabled = true;
            typingIndicator.style.display = 'flex';
            chatArea.scrollTop = chatArea.scrollHeight;

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        message: message,
                        user_id: userId,
                        session_id: sessionId
                    })
                });

                const data = await response.json();
                typingIndicator.style.display = 'none';

                if (data.response) {
                    appendMessage(data.response, false);
                } else {
                    appendMessage('Error: No response from agent.', false);
                }

                if (data.interrupt) {
                    showHILControls(data.interrupt);
                }
            } catch (err) {
                typingIndicator.style.display = 'none';
                appendMessage('Failed to communicate with service.', false, 'info');
                console.error(err);
            } finally {
                messageInput.disabled = false;
                sendBtn.disabled = false;
                messageInput.focus();
            }
        }

        function showHILControls(interrupt) {
            const controlsDiv = document.createElement('div');
            controlsDiv.className = 'hil-actions';
            controlsDiv.innerHTML = `
                <button class="hil-btn approve" onclick="sendDecision('approve', this)">🟢 Approve</button>
                <button class="hil-btn reject" onclick="sendDecision('reject', this)">🔴 Reject</button>
            `;
            chatArea.appendChild(controlsDiv);
            chatArea.scrollTop = chatArea.scrollHeight;
        }

        async function sendDecision(decision, btnElement) {
            // Remove quick action buttons
            const parent = btnElement.parentElement;
            parent.remove();

            appendMessage(decision, true);
            messageInput.disabled = true;
            sendBtn.disabled = true;
            typingIndicator.style.display = 'flex';
            chatArea.scrollTop = chatArea.scrollHeight;

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        message: decision,
                        user_id: userId,
                        session_id: sessionId
                    })
                });

                const data = await response.json();
                typingIndicator.style.display = 'none';

                if (data.response) {
                    appendMessage(data.response, false);
                }
            } catch (err) {
                typingIndicator.style.display = 'none';
                appendMessage('Failed to submit decision.', false, 'info');
                console.error(err);
            } finally {
                messageInput.disabled = false;
                sendBtn.disabled = false;
                messageInput.focus();
            }
        }
    </script>
</body>
</html>"""

# Remove any default root routes that redirect to /dev-ui/ so we can serve our own Web Chat UI at /
for r in list(app.routes):
    if r.path == "/":
        app.routes.remove(r)

@app.get("/", response_class=HTMLResponse)
async def get_chat_interface():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    message = body.get("message")
    user_id = body.get("user_id", "web-user")
    session_id = body.get("session_id", str(uuid.uuid4()))

    try:
        # Check if it's already JSON
        json.loads(message)
        payload_text = message
    except ValueError:
        if message.lower() in ("approve", "reject", "yes", "no"):
            payload_text = message
        else:
            # Use Gemini to parse natural language to JSON
            try:
                from google.genai import Client
                genai_client = Client()
                response = genai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=(
                        "You are a parser. Convert this natural language expense report into a structured JSON string matching the keys: "
                        "'amount' (float), 'submitter' (string), 'category' (string), 'description' (string), 'date' (string, YYYY-MM-DD format, use '2026-06-27' if no date specified). "
                        "Wrap the resulting dictionary under a parent key 'data'. Output ONLY raw JSON, do not include markdown backticks or any other text.\n\n"
                        f"User Input: {message}"
                    ),
                )
                parsed_json = response.text.strip()
                if parsed_json.startswith("```"):
                    parsed_json = parsed_json.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
                json.loads(parsed_json)
                payload_text = parsed_json
            except Exception as e:
                import re
                amounts = re.findall(r"\d+(?:\.\d+)?", message)
                amount = float(amounts[0]) if amounts else 0.0
                payload_text = json.dumps({
                    "data": {
                        "amount": amount,
                        "submitter": "Unknown",
                        "category": "General",
                        "description": message,
                        "date": "2026-06-27"
                    }
                })

    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=payload_text)]
    )

    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        memory_service=memory_service,
        artifact_service=artifact_service,
        app_name="expense_agent",
        auto_create_session=True,
    )

    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
        run_config=RunConfig(streaming_mode=StreamingMode.NONE),
    ):
        events.append(event)

    outputs = []
    interrupt = None
    for e in events:
        if e.output:
            outputs.append(str(e.output))
        if e.content and e.content.parts:
            for part in e.content.parts:
                if part.text:
                    outputs.append(part.text)
        if e.tool_calls:
            for tc in e.tool_calls:
                if tc.name == "adk_request_input":
                    interrupt = tc.args
                    if isinstance(tc.args, dict) and "message" in tc.args:
                        outputs.append(tc.args["message"])

    # Remove duplicates or overlapping content while preserving order
    unique_outputs = []
    for output in outputs:
        if output not in unique_outputs:
            unique_outputs.append(output)

    # Format output text to be clean HTML/newlines
    response_text = "<br>".join(unique_outputs) if unique_outputs else "No response generated."

    return {
        "user_id": user_id,
        "session_id": session_id,
        "response": response_text,
        "interrupt": interrupt,
    }

@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
