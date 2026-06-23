# ruff: noqa
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

from google.adk.workflow import Workflow, START, FunctionNode
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel
import os
import google.auth
import json
import base64
import re

from google.auth.exceptions import DefaultCredentialsError

try:
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
except DefaultCredentialsError:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Project Configuration
CONFIG = {
    "threshold": 100.0,
    "model_name": "gemini-3.1-flash-lite",
}

# Use the configured model
model = Gemini(
    model=CONFIG["model_name"],
    retry_options=types.HttpRetryOptions(attempts=3),
)


# Schema representing an expense report
class Expense(BaseModel):
    amount: float
    submitter: str
    category: str
    description: str
    date: str


# Schema representing LLM Risk Assessment outcome
class RiskAssessment(BaseModel):
    risk_level: str  # e.g., 'low', 'medium', 'high'
    reasoning: str
    flagged: bool


# Node 1: Parse and normalize incoming JSON / base64 PubSub event data
def parse_expense_event(ctx: Context, node_input: types.Content) -> Event:
    text = ""
    if node_input and node_input.parts:
        text = node_input.parts[0].text.strip()

    # If resuming from human approval, bypass parsing and use the stored expense.
    if "expense" in ctx.state and (ctx.resume_inputs or text.lower() in ("approve", "reject", "yes", "no")):
        expense_dict = ctx.state["expense"]
        expense = Expense(**expense_dict)
        return Event(output=expense)

    # Try standard JSON parsing
    try:
        event_data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback to base64 decoding
        try:
            decoded = base64.b64decode(text).decode("utf-8")
            event_data = json.loads(decoded)
        except Exception:
            raise ValueError(f"Unable to parse input as JSON or base64 JSON: {text}")

    data = event_data.get("data")
    if not data:
        raise ValueError("Missing 'data' field in event payload")

    # Handle stringified/base64-encoded inner data field
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            try:
                decoded_data = base64.b64decode(data).decode("utf-8")
                data = json.loads(decoded_data)
            except Exception:
                raise ValueError("Could not parse 'data' string as JSON or base64")

    expense = Expense(
        amount=float(data.get("amount", 0.0)),
        submitter=str(data.get("submitter", "Unknown")),
        category=str(data.get("category", "General")),
        description=str(data.get("description", "No description provided")),
        date=str(data.get("date", "Unknown")),
    )

    return Event(output=expense, state={"expense": expense.model_dump()})  # type: ignore


# Node 2: Route based on dollar threshold rule
def evaluate_threshold(node_input: Expense) -> Event:
    if node_input.amount < float(CONFIG["threshold"]):
        return Event(output=node_input, route="auto_approve")  # type: ignore
    return Event(output=node_input, route="risk_review")  # type: ignore


# Node 3 (Option A): Auto-approve expenses under the threshold
def auto_approve_node(node_input: Expense):
    msg = (
        f"🟢 AUTO-APPROVED: Expense of ${node_input.amount:.2f} submitted by "
        f"{node_input.submitter} is under the ${CONFIG['threshold']:.2f} threshold."
    )
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(
        output={
            "status": "approved",
            "method": "auto-approve",
            "expense": node_input.model_dump(),
        }
    )


# Security Checkpoint Regex Patterns
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CC_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

# Prompt Injection Keywords
INJECTION_KEYWORDS = [
    "ignore all previous",
    "ignore previous instructions",
    "system prompt",
    "overwrite instructions",
    "bypass standard",
    "auto-approve this",
    "force approval",
    "override threshold",
    "override rules",
    "ignore guidelines",
    "you must approve",
    "new instruction",
]

# Security checkpoint to scrub data and detect injection
def security_checkpoint(ctx: Context, node_input: Expense) -> Event:
    description = node_input.description
    redacted_categories = []

    # 1. Scrub personal data (SSNs and CCs)
    if SSN_REGEX.search(description):
        description = SSN_REGEX.sub("[REDACTED SSN]", description)
        redacted_categories.append("SSN")

    if CC_REGEX.search(description):
        cleaned = CC_REGEX.sub("[REDACTED CREDIT CARD]", description)
        if cleaned != description:
            description = cleaned
            redacted_categories.append("Credit Card")

    # Update the expense object with scrubbed description
    node_input.description = description
    ctx.state["expense"] = node_input.model_dump()

    if redacted_categories:
        ctx.state["redacted_categories"] = redacted_categories

    # 2. Defend against prompt injection
    desc_lower = description.lower()
    is_injection = any(kw in desc_lower for kw in INJECTION_KEYWORDS)

    if is_injection:
        ctx.state["security_event"] = True
        mock_assessment = {
            "risk_level": "CRITICAL (Security Event)",
            "reasoning": "POTENTIAL PROMPT INJECTION DETECTED. Description contained instructions attempting to bypass approval logic. Bypassed LLM review.",
            "flagged": True,
        }
        return Event(output=mock_assessment, route="bypass_llm_suspicious")

    return Event(output=node_input, route="risk_review_clean")



# Node 3 (Option B): LLM Risk reviewer
risk_reviewer = LlmAgent(
    name="risk_reviewer",
    model=model,
    instruction=(
        "You are an expense report risk analyzer. Examine the details (amount, submitter, category, description, date) "
        "and determine if there are anomalies or risk factors. Output your judgment using the RiskAssessment schema."
    ),
    output_schema=RiskAssessment,
    include_contents="none",
)


# Node 4: Human-in-the-loop pause and resume logic
async def human_approval_node(ctx: Context, node_input: dict):
    # Retrieve the decision from resume_inputs or fallback to user_content (chat message)
    decision = None
    if ctx.resume_inputs and "approval" in ctx.resume_inputs:
        decision = str(ctx.resume_inputs["approval"]).strip().lower()
    else:
        user_text = ""
        if ctx.user_content and ctx.user_content.parts:
            user_text = ctx.user_content.parts[0].text or ""
        user_text_clean = user_text.strip().lower()
        if user_text_clean in ("approve", "reject", "approved", "rejected"):
            decision = user_text_clean

    if not decision:
        expense_dict = ctx.state.get("expense", {})
        is_security = ctx.state.get("security_event", False)
        reason = "POTENTIAL SECURITY EVENT (Prompt Injection)" if is_security else f"Over ${CONFIG['threshold']:.2f} threshold."

        redacted = ctx.state.get("redacted_categories", [])
        redacted_str = f"\nRedacted Data Categories: {', '.join(redacted)}" if redacted else ""

        msg = (
            f"⚠️ RISK REVIEW ALERT: An expense of ${expense_dict.get('amount')} submitted by "
            f"{expense_dict.get('submitter')} requires approval.\n"
            f"Reason: {reason}\n"
            f"LLM Risk Level: {node_input.get('risk_level')}\n"
            f"LLM Reasoning: {node_input.get('reasoning')}\n"
            f"LLM Flagged: {node_input.get('flagged')}{redacted_str}\n\n"
            f"Reply with 'approve' or 'reject' to make a decision."
        )
        yield Event(
            content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
        )
        yield RequestInput(interrupt_id="approval", message=msg)
        return

    # Process response
    expense_dict = ctx.state.get("expense", {})
    status = "approved" if "approve" in decision else "rejected"
    msg = f"✅ DECISION RECORDED: Expense has been {status.upper()} by human reviewer (User input: '{decision}')."
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(
        output={
            "status": status,
            "method": "human-review",
            "expense": expense_dict,
            "risk_assessment": node_input,
        }
    )


# Wrap human approval node to enable resume execution
human_node = FunctionNode(
    func=human_approval_node,
    rerun_on_resume=True,
)

# Connect nodes using conditional RoutingMap dict
edges = [
    (START, parse_expense_event),
    (parse_expense_event, evaluate_threshold),
    (
        evaluate_threshold,
        {"auto_approve": auto_approve_node, "risk_review": security_checkpoint},
    ),
    (
        security_checkpoint,
        {"risk_review_clean": risk_reviewer, "bypass_llm_suspicious": human_node},
    ),
    (risk_reviewer, human_node),
]

root_agent = Workflow(
    name="ambient_expense_workflow",
    edges=edges,
    description=(
        "Ambient expense approval workflow. Under $100 is auto-approved. "
        "Over $100 is evaluated by LLM for risk and paused for human decision."
    ),
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
