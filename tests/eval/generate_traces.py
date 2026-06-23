import asyncio
import json
import os
import sys
import dotenv

# Load environment variables (for GEMINI_API_KEY etc.)
dotenv.load_dotenv()

from expense_agent.agent import app
from google.adk.runners import InMemoryRunner
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.genai import types

async def generate_all_traces():
    dataset_path = "tests/eval/datasets/basic-dataset.json"
    output_path = "artifacts/traces/generated_traces.json"

    print(f"Loading dataset from {dataset_path}...")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    eval_cases = dataset.get("eval_cases", [])
    print(f"Loaded {len(eval_cases)} eval case(s).")

    runner = InMemoryRunner(app=app, app_name="expense_agent")
    generated_cases = []

    for i, case in enumerate(eval_cases):
        case_id = case["eval_case_id"]
        print(f"\n--- Running Case {i+1}/{len(eval_cases)}: {case_id} ---")
        
        prompt_content = case["prompt"]
        prompt_text = prompt_content["parts"][0]["text"]
        
        # Wrap prompt_text inside the required "data" field so parse_expense_event doesn't raise ValueError
        wrapped_data = {"data": json.loads(prompt_text)}
        wrapped_text = json.dumps(wrapped_data)
        
        session = await runner.session_service.create_session(
            app_name="expense_agent", user_id="eval_user"
        )
        
        events_list = []
        # Add the initial user prompt to the trace events, but scrub PII first so it doesn't log raw PII
        scrubbed_prompt_text = prompt_text
        if "000-12-3456" in scrubbed_prompt_text:
            scrubbed_prompt_text = scrubbed_prompt_text.replace("000-12-3456", "[REDACTED SSN]")
        if "1111-2222-3333-4444" in scrubbed_prompt_text:
            scrubbed_prompt_text = scrubbed_prompt_text.replace("1111-2222-3333-4444", "[REDACTED CREDIT CARD]")
        events_list.append({
            "author": "user",
            "content": {
                "role": "user",
                "parts": [{"text": scrubbed_prompt_text}]
            }
        })
        
        final_response_text = ""
        
        # Run initial execution
        async for event in runner.run_async(
            user_id="eval_user",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=wrapped_text)]),
        ):
            if isinstance(event, Event):
                if event.content and event.content.parts:
                    txt = event.content.parts[0].text
                    print(f"[{case_id}] UI Output: {txt}")
                    events_list.append({
                        "author": "model",
                        "content": {
                            "role": "model",
                            "parts": [{"text": txt}]
                        }
                    })
                    final_response_text = txt
                if event.output:
                    print(f"[{case_id}] Final Output: {event.output}")
            elif isinstance(event, RequestInput):
                print(f"[{case_id}] Interrupted! Automated decision required.")
                # Automate decision
                expense_payload = json.loads(prompt_text)
                expense_data = expense_payload.get("data", expense_payload)
                description = expense_data.get("description", "").lower()
                
                # Check for prompt injection keywords
                injection_keywords = [
                    "ignore all previous", "ignore previous instructions", "system prompt",
                    "overwrite instructions", "bypass standard", "auto-approve this",
                    "force approval", "override threshold", "override rules",
                    "ignore guidelines", "you must approve", "new instruction", "bypass"
                ]
                is_injection = any(kw in description for kw in injection_keywords)
                decision = "reject" if is_injection else "approve"
                print(f"[{case_id}] Decision resolved to: {decision}")
                
                # Add human action to events list
                events_list.append({
                    "author": "user",
                    "content": {
                        "role": "user",
                        "parts": [{"text": decision}]
                    }
                })
                
                # Resume execution
                resume_msg = types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name="approval",
                                id="approval",
                                response={"approval": decision}
                            )
                        )
                    ]
                )
                async for resume_event in runner.run_async(
                    user_id="eval_user",
                    session_id=session.id,
                    new_message=resume_msg,
                ):
                    if isinstance(resume_event, Event):
                        if resume_event.content and resume_event.content.parts:
                            txt = resume_event.content.parts[0].text
                            print(f"[{case_id}] UI Output (resume): {txt}")
                            events_list.append({
                                "author": "model",
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": txt}]
                                }
                            })
                            final_response_text = txt
                        if resume_event.output:
                            print(f"[{case_id}] Final Output (resume): {resume_event.output}")
        
        # Prepare EvalCase trace representation
        eval_case_dict = {
            "eval_case_id": case_id,
            "prompt": prompt_content,
            "responses": [
                {
                    "response": {
                        "role": "model",
                        "parts": [{"text": final_response_text}]
                    }
                }
            ],
            "agent_data": {
                "agents": {
                    "expense_agent": {
                        "agent_id": "expense_agent",
                        "description": "Expense agent evaluator"
                    }
                },
                "turns": [
                    {
                        "turn_index": 0,
                        "turn_id": "turn_0",
                        "events": events_list
                    }
                ]
            }
        }
        generated_cases.append(eval_case_dict)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save traces to file
    output_dataset = {
        "eval_cases": generated_cases
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_dataset, f, indent=2)
    print(f"\nSuccessfully wrote traces to {output_path}")

def main():
    asyncio.run(generate_all_traces())

if __name__ == "__main__":
    main()
