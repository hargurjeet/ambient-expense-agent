# Workspace Customization & Context

This file contains the current state, deployment details, and history of the **Ambient Expense Approval Agent** project. It serves to maintain context across sessions.

---

## 🚀 Live Deployment Status

- **Google Cloud Project ID**: `expense-agent-500315`
- **GCP Region**: `us-central1`
- **Live Cloud Run URL**: [https://ambient-expense-agent-639117196486.us-central1.run.app](https://ambient-expense-agent-639117196486.us-central1.run.app)
- **Pub/Sub Trigger Endpoint**: `https://ambient-expense-agent-639117196486.us-central1.run.app/apps/expense_agent/trigger/pubsub`
- **GitHub Repository**: [https://github.com/hargurjeet/ambient-expense-agent](https://github.com/hargurjeet/ambient-expense-agent) (Public)
- **Secrets Configured**: `GEMINI_API_KEY` stored securely in GCP Secret Manager, linked to Cloud Run revision with proper `Secret Manager Secret Accessor` IAM permissions granted to `639117196486-compute@developer.gserviceaccount.com`.

---

## 📈 Evaluation Setup & Performance

- **Synthetic Dataset**: Located at `tests/eval/datasets/basic-dataset.json` (5 diverse test cases including PII SSN/CC leaks and prompt injections).
- **Trace Generator**: `tests/eval/generate_traces.py` runs evaluations locally using the `InMemoryRunner` and intercepts inputs to automate decisions.
- **Judge Configurations**: Configured in `tests/eval/eval_config.yaml` using local Python functions calling `gemini-2.5-flash` with `GEMINI_API_KEY`.
- **Grade CLI Wrapper**: `tests/eval/grade_traces.py` mocks out GCP ADC credential requirements to allow purely local evaluation.
- **Baseline Evaluation Results**:
  * **Routing Correctness**: `5.00 / 5.00`
  * **Security Containment**: `5.00 / 5.00`
  * **Report**: Documented in `evaluation_report.md` (and inside the `artifacts/grade_results/` logs).

---

## 🧑‍💻 Useful Commands

* **Local Verification**: `make run` launches the FastAPI web service locally on port 8080.
* **Generate Traces**: `make generate-traces`
* **Run Evaluation Grading**: `make grade`
