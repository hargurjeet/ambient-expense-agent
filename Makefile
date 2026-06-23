.PHONY: install playground run generate-traces grade

install:
	uv sync

playground:
	uv run agents-cli playground

run:
	uv run python expense_agent/fast_api_app.py

generate-traces:
	uv run python tests/eval/generate_traces.py

grade:
	uv run --with google-agents-cli python tests/eval/grade_traces.py --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml

