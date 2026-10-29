PYTHON ?= python3
.PHONY: help test test-frontend check
help:
	@echo 'make test: portable Python/API tests; TEST_DATABASE_URL enables PostgreSQL regressions'
	@echo 'make test-frontend: PHP lint and existing PHPUnit tests (see docs/TESTING.md)'
	@echo 'Local OVA runner: docs/LOCAL-APPLIANCE.md; update workflow: docs/UPDATES.md'
test:
	$(PYTHON) tools/check.py
test-frontend:
	$(PYTHON) tools/check.py --frontend
check: test
	git diff --check
