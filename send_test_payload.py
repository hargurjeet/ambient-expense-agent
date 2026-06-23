import requests
import json

BASE_URL = "http://127.0.0.1:8080"
user_id = "user"

# 1. Create a session
session_url = f"{BASE_URL}/apps/expense_agent/users/{user_id}/sessions"
response = requests.post(session_url, json={}, headers={"Content-Type": "application/json"})
session_id = response.json()["id"]
print(f"Created Session ID: {session_id}")

# 2. Send the test expense payload
payload = {
    "amount": 150.0,
    "submitter": "alice@company.com",
    "category": "software",
    "description": "IDE License",
    "date": "2026-06-06"
}

data = {
    "app_name": "expense_agent",
    "user_id": user_id,
    "session_id": session_id,
    "new_message": {
        "role": "user",
        "parts": [{"text": json.dumps({"data": payload})}],
    },
    "streaming": True,
}

print("Sending test expense payload...")
response = requests.post(f"{BASE_URL}/run_sse", json=data, stream=True)
print(f"Response status: {response.status_code}")

for line in response.iter_lines():
    if line:
        line_str = line.decode("utf-8")
        if line_str.startswith("data: "):
            print(line_str)
