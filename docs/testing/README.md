# Local test workflow

The complete acceptance plan, case catalogue, function inventory and evidence
workflow are in [TEST-CONCEPT.md](TEST-CONCEPT.md).

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
`Authentication-Token` header. Readiness requires a successful startup-cleanup receipt and PostgreSQL
connectivity; it does not certify the whole platform. API errors do not return exception strings.
Malformed identifiers return HTTP 400, oversized bodies 413, failed operations
500 and database unavailability 503. Successful existing route payloads remain
compatible. HTTP redirects use 307 to preserve POST bodies and query strings.

Set `TEST_DATABASE_URL` to a **disposable PostgreSQL administrator connection**
to enable the database contracts. They create separate databases and restricted
roles, then remove them afterwards; never use production credentials.
The Linux DHCP/host-input tests also need `dnsmasq`. The privileged network test
has an explicit opt-in: see `HEIST_PRIVILEGED_TESTS` in its test source.
It creates a private network namespace; never enable it on production. Missing
opt-ins are reported as skips, not successful coverage. CI runs portable/API
and PostgreSQL tests; privileged VM acceptance belongs on a local workstation.

## Web application

The maintained web application uses React and Flask. Run `make test-frontend`
(or `make test-ui`) for strict TypeScript and transport tests, then
`make test-ui-browser` for the production build and isolated browser fixtures.
See [FRONTEND.md](../development/FRONTEND.md). The PHP tree, Composer dependencies and PHPUnit
CI job have been removed. Flask contract tests are part of `tools/check.py` and
include disposable PostgreSQL authorization/session/grading checks.

`tests/end-to-end/` contains the existing Playwright UI tests. They and
`tests/integration/platform/` perform live actions (including user/challenge deletion and
Proxmox calls); they are **integration tests**, despite older unit-test labels.
Run them only against the disposable [local appliance](LOCAL-APPLIANCE.md), with
its test credentials/configuration. They are intentionally excluded from the
portable unit discovery. `tests/performance/` remains opt-in load testing.

A release needs actual login/upload/create/launch/solve/grade/teardown checks,
two concurrent students with cross-instance denial checks, and an independent
cold import. Mocked API services, successful HTTP health checks and compilation
alone do not prove those behaviors. Retain failure logs as well as final results.

Recorded local results and remaining gaps: [LOCAL-VALIDATION.md](../validation/legacy-appliance.md).

## Audit an external production database dump

`tools/local/rehearse_migrations.py` can restore a private external custom-format
PostgreSQL dump into a new scratch database on the isolation-verified disposable
pilot. Use the source server's PostgreSQL major version to create and read the
dump. The runner requires a root-owned mode-0600 input, the reviewed SHA256 and
original source commit. It never migrates the installed or production database.

Supply `--baseline-dump`, `--baseline-sha256` and `--baseline-source` together with
the ordinary private fixture `--config` and new `--output` directory. A source
not declared by the release manifest additionally requires the explicit
`--audit-unsupported-source` flag. That flag permits only this scratch SQL audit:
it does not change the manifest or bypass installation/rollout admission.

The audit tests actual migration-body failure rollback, protected row/schema
preservation, restricted-role access, session invalidation, personalized flag generation against
the restored grader, and scratch database
restoration. Its receipt records whether the starting commit was declared
supported. Complete VM/host acceptance and review of local source changes remain
separate requirements.

The personalized-flag receipt records `tested` and `flags_checked`; an empty
fixture is explicitly untested. It checks one existing account and all stored
personalized flag definitions, without writing to guests, accepting a submission
or printing flag secrets. Cross-account denial and both legacy email and upstream
unique-ID graders also have disposable database integration tests.
