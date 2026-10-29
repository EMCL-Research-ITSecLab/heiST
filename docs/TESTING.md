# Local test workflow

Start with a disposable virtual environment and the existing platform dependency
subset, then run from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
make test PYTHON=.venv/bin/python
```

The runner discovers `tests/test_*.py`, including Flask routing/authentication,
input validation, health checks, release rollback, OVA packaging and existing
backend regressions. Imports do not create log directories or connect to
Proxmox. Injected API services exercise real Flask requests without live VMs.
Both `/health/live` and `/health/ready` require HTTPS and the existing
`Authentication-Token` header. Readiness checks PostgreSQL connectivity, not
whole-platform readiness. API errors do not return exception strings.
Malformed identifiers return HTTP 400, oversized bodies 413, failed operations
500 and database unavailability 503. Successful existing route payloads remain
compatible. HTTP redirects use 307 to preserve POST bodies and query strings.

Set `TEST_DATABASE_URL` to a **disposable PostgreSQL database** to enable seven
ownership/concurrency tests. They create random schemas and remove them afterwards.
The Linux DHCP/host-input tests also need `dnsmasq`. The privileged network test
has an explicit opt-in: see `HEIST_PRIVILEGED_TESTS` in its test source.
It creates a private network namespace; never enable it on production. Missing
opt-ins are reported as skips, not successful coverage. CI runs portable/API
and PostgreSQL tests; privileged VM acceptance belongs on a local workstation.

## Web application

The PHP application already has PHPUnit and Composer dependencies; no frontend
framework is introduced. Install those existing dependencies as described by
the web application's Composer file. From a workstation with PHP and the
`webserver/html/vendor/` directory present:

```sh
make test-frontend PYTHON=.venv/bin/python
```

This lints maintained PHP files then runs the existing `phpunit.xml` suite.
Warnings and deprecations fail the command. The bootstrap rebases application
class mappings when an external vendor cache is reused, so the current source
is tested rather than a different installed release.
Container-backed methods are explicitly tagged `database` and excluded by
default. To include them, run `python3 tools/check.py --frontend
--frontend-database` on a disposable host with Docker and a cached `postgres:15`
image. Those tests create their own databases; they must never use production
credentials. Inspect the PHPUnit summary before claiming database coverage.
The command fails if the PHP runtime or PHPUnit is missing; it never installs
packages silently. Frontend runtime tests are separate from Python API tests.

`tests/end-to-end/` contains the existing Playwright UI tests. They and
`backend/tests/` perform live actions (including user/challenge deletion and
Proxmox calls); they are **integration tests**, despite older unit-test labels.
Run them only against the disposable [local appliance](LOCAL-APPLIANCE.md), with
its test credentials/configuration. They are intentionally excluded from the
portable unit discovery. `tests/performance/` remains opt-in load testing.

A release needs actual login/upload/create/launch/solve/grade/teardown checks,
two concurrent students with cross-instance denial checks, and an independent
cold import. Mocked API services, successful HTTP health checks and compilation
alone do not prove those behaviors. Retain failure logs as well as final results.

Recorded local results and remaining gaps: [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md).
