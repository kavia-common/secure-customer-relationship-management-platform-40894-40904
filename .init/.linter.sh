#!/bin/bash
cd /home/kavia/workspace/code-generation/secure-customer-relationship-management-platform-40894-40904/crm_fastapi_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

