.PHONY: bootstrap generate batch serve test lint demo
bootstrap:
	./scripts/bootstrap.sh
generate:
	.venv/bin/experience-reco generate
batch:
	.venv/bin/experience-reco batch
serve:
	.venv/bin/uvicorn experience_reco.api:create_app --factory --host 127.0.0.1 --port 8000
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests scripts/update_readme_metrics.py
	.venv/bin/ruff format --check src tests scripts/update_readme_metrics.py
demo: generate batch
	@echo 'Ready: run make serve, then open http://127.0.0.1:8000/docs'
