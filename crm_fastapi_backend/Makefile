# Regenerate OpenAPI schema for the FastAPI backend
# Usage:
#   make openapi
# This will write interfaces/openapi.json

OPENAPI_OUT=interfaces/openapi.json

.PHONY: openapi
openapi:
	@if [ -x "./venv/bin/python" ]; then ./venv/bin/python -m src.api.generate_openapi; else python -m src.api.generate_openapi; fi
	@echo "OpenAPI schema written to $(OPENAPI_OUT)"
