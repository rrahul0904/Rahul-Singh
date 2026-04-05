PYTHON ?= python3

.PHONY: run-integrated run-stateful run-stateful-phase2 test-api check-routes

run-integrated:
	uvicorn apps.api.app.main_integrated:app --host 0.0.0.0 --port 8001

run-stateful:
	uvicorn apps.api.app.main_stateful:app --host 0.0.0.0 --port 8002

run-stateful-phase2:
	uvicorn apps.api.app.main_stateful_phase2:app --host 0.0.0.0 --port 8003

test-api:
	pytest apps/api/tests

check-routes:
	$(PYTHON) scripts/check_routes.py
