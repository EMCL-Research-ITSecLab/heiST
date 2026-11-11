PYTHON ?= python3
.PHONY: help test test-frontend check
help:
	@echo 'make test: portable Python/API tests; TEST_DATABASE_URL enables PostgreSQL regressions'
	@echo 'make test-frontend: React/TypeScript and browser transport tests'
	@echo 'Local OVA runner: docs/testing/LOCAL-APPLIANCE.md; update workflow: docs/administration/UPDATES.md'
test:
	$(PYTHON) tools/check.py
test-frontend: test-ui
check: test
	git diff --check

.PHONY: test-ui build-ui test-ui-browser
test-ui:
	npm --prefix frontend run check
build-ui:
	npm --prefix frontend run build
test-ui-browser: build-ui
	$(PYTHON) tests/browser/ui_smoke.py
	$(PYTHON) tests/browser/ui_layout.py
	$(PYTHON) -m unittest tests.browser.ui_management
