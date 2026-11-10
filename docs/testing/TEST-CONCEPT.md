# Platform verification and release acceptance

The acceptance target is one exact source commit, its complete artifacts and a
recorded production starting revision. A successful health endpoint or a coverage
percentage does not prove an exercise, an update or a restore works. This concept
combines contract tests, real infrastructure rehearsals and independent restore
checks. Missing prerequisites and untested paths remain visible release blockers.

The [monitoring acceptance matrix](MONITORING.md) expands sensor, command,
network, ingestion, Grafana, archive and independent-alert validation. Service
inventory results and complete end-to-end acceptance are separate evidence.

## Inventory and traceability

[The machine-readable catalogue](../../verification/cases.json) defines the required
areas, procedures, expected results and evidence. Every portable Python test
module must be mapped. `python3 -m tools.verification catalogue` detects missing
modules, invalid source links and incomplete/duplicate case definitions.

The catalogue includes installation, packaging, cloud distribution, authentication,
permissions, profiles, browser behavior, accessibility, artifact validation,
challenge creation, warm/cold assignment, Windows/AD, concurrent students,
network isolation, grading, expiry, monitoring, archiving, administrator actions,
upgrades, rollback, independent recovery, capacity and tutor materials.

Inventory every named Python function, including methods and nested functions:

```sh
python3 -m tools.function_inventory --output /tmp/heist-functions.json
python3 tools/check.py --function-trace /tmp/heist-function-execution.json
```

The trace records execution in this process; subprocesses, remote guests and SQL
need their own traces/results. An executed function remains **unverified** until
a reviewed mapping identifies passing tests and explains their behavioral
assertions. Test doubles that only reproduce the implementation are insufficient.
Review positive behavior, invalid input, boundaries, dependency failure, resource
cleanup and unauthorized use for each function. Unreachable/dead functions should
be removed. Fixture setup and branch execution do not count as semantic proof.

As the backend is reorganized, move the function's contract tests with it. The
PHP replacement is a release gate: all maintained browser contracts, background
workers, installer/update adapters and old authentication/data formats must work
through Flask before the PHP tree and runtime can be retired.

## Test environments

| Layer | Environment | Required evidence |
|---|---|---|
| Pure functions/API contracts | Disposable Python environment; injected external boundaries | Inputs, outputs, error/cleanup assertions; function inventory |
| Database/concurrency | Fresh PostgreSQL database and real restricted application role | Migration/function results, races, privilege denial, cleanup |
| Browser contracts | Production React build, Chromium/Firefox/WebKit, isolated API fixtures | All routes/actions, request payloads, accessibility interactions, failures |
| Application integration | Real Flask API + PostgreSQL + reverse proxy; dedicated accounts | Session/cookie/CSRF behavior, upload and data persistence, role revocation |
| VM/challenge integration | Isolated nested Proxmox on silverstone, canonical `/mnt/data/heist-builds` | Source/artifact IDs, boot/network proof, full student lifecycle |
| Archive integration | Separate disposable archive VM and source fixtures | Real systemd timer/credentials/SSH, failures, receipt and sample restore |
| Release recovery | Isolated restored production clone with separate backup volume | Complete successful update, fault matrix, rollback/newer-data recovery/reboot |
| Capacity/curriculum | Class-sized isolated load and clean tutor/student imports | Agreed SLOs/resources; exercise sheets/walkthroughs solved from scratch |

Production credentials and production networks never serve as test fixtures.
A local test pass must identify which layer ran. Record OS, Python, PostgreSQL,
browser, Proxmox, VM resources, storage layout, network restrictions and clocks.

## Evidence collection

Use the existing dependencies; the tooling does not install packages or start VMs.
Choose a new private output directory for each run:

```sh
python3 -m tools.verification run --suite python --output /tmp/heist-evidence/python
python3 -m tools.verification run --suite ui --output /tmp/heist-evidence/ui
python3 -m tools.verification run --suite ui-build --output /tmp/heist-evidence/build
python3 -m tools.verification run --suite browser --output /tmp/heist-evidence/browser
```

The application has no PHP dependency. Flask/React contracts replace the removed
PHP suite; legacy VM migration and recovery still require appliance acceptance. Reports contain the commit, dirty-tree
state, command, exit status, timestamps, duration and artifact checksums. Logs and
results are private. Do not publish raw evidence without reviewing it for fixture
credentials or solutions. Evidence written from an uncommitted checkout is useful
for development and deliberately rejected as release evidence.

For the release Python gate, provide `TEST_DATABASE_URL` for the fresh database,
install the documented system tools and explicitly enable
`HEIST_PRIVILEGED_TESTS=1` on the disposable private-network fixture. Then use
`--strict`: skipped/expected-failure cases fail the gate. Verify evidence with:

```sh
python3 -m tools.verification verify-evidence /path/python --commit FULL_SHA --strict
```

This verifies **one suite**, never whole-platform approval. It detects changed
logs/results, wrong commits, source changes during the run and missing strict
prerequisites. The receipt is an integrity record, not a cryptographic attestation
from an independent verifier. The release reviewer must establish its provenance.

## Test design for each feature

For each operation define the allowed actors, initial state, input, expected state
transition, durable effects, observable response and forbidden side effects. Test:

1. Normal operation, minimum/maximum values, empty data and a realistic large set.
2. Malformed JSON/forms, invalid IDs/types/Unicode, missing and duplicate fields,
   oversized requests and malicious filenames/XML/tar members.
3. Anonymous/student/owner/other-owner/admin/revoked-admin/forced-reset identities.
4. Concurrent requests, retries, duplicate delivery, stale browser state and
   interruption before and after the commit point.
5. Database/SSH/API/storage/clock/TLS failure, timeout, disk or inode exhaustion.
6. Resource release: connections, locks, temporary files, IPs, VMs, jobs, sessions,
   reservations and uploaded artifacts. Repeat after process/VM reboot.
7. Independent evidence that unrelated accounts, grades, files and networks remain
   unchanged. Use protected-table hashes and fixtures with unique identities.

Every claimed fix needs a regression that would fail with the original behavior.
Use real PostgreSQL for transactional ownership, constraints and migration tests.
Mock VM/SSH boundaries for fast validation, then exercise those boundaries against
real disposable VMs. Never replace the real lifecycle acceptance with mocks.

## Mandatory lifecycle and failure matrices

For each challenge type exercise inactive → available → provisioning → READY →
assigned → active → expired/terminated, including cancellation at every supported
transition. Verify cold/warm starts, student-specific flags, all hints, partial and
complete grading, time extensions, VPN/DNS/DHCP, restart, retirement/restoration,
and full deletion. Repeat ownership races with two students and multiple workers.

For each release phase inject failure immediately before and after the phase:
preflight, maintenance gate, writer drain, SQL dump, each VM checkpoint, source
checkout, dependency/runtime artifact installation, static asset installation,
each migration, service activation, health/data checks, durable commit and public
reopening. Before commit verify baseline restoration; after commit verify
non-destructive completion. Reconcile ambiguous Proxmox tasks explicitly. Test
manual rollback with newer student data and restore that newer safety checkpoint
independently. Reboot under the maintenance gate.

For the archive VM test timer catch-up, source outage, changed host key, wrong
key, corrupt/changed file, repeated identical file, same filename with different
content, overlapping runs, missing destination mount, capacity exhaustion and
process termination. A failed/stale/unknown receipt is never shown as successful.
Restore sampled archived files and verify digests outside the archive directory.

## Release decision

Release acceptance requires all required catalogue cases to pass on the final
commit and final artifacts; no unexplained skips, unverified supported functions,
unknown failures or untested database/role migrations may be hidden by the
aggregate test count. A documented exception needs an owner, exact affected case,
impact, expiry and explicit release approval; it is not a passing test.

The signed review record must link source and artifact hashes, supported starting
revision, environment inventory, suite receipts, function/assertion mappings,
appliance and recovery evidence, capacity limits, tutor checks, open exceptions,
and administrator runbooks. Keep a rollback/restore decision and independent
backup available during the scheduled maintenance window.

The current catalogue is the verification plan, not a claim that every case has
already passed. Existing historical appliance evidence applies only to the
revisions named in [ROLLOUT-VALIDATION.md](../validation/rollouts.md). Repeat affected
acceptance after architecture, dependency, schema or deployment changes.


## Frontend regression and real database checks

The browser fixture suite now includes populated states at five viewport widths
in both themes, maximum-length unbroken text, exact restore endpoint selection,
paging/filter reset, dialog cancellation and focus return, mobile keyboard access,
theme persistence and primary button contrast. Documentation captures are built
from the same production UI and synthetic records, then checked against source
and PNG hashes. See [UI verification](UI-VERIFICATION.md).

A separate HTTPS Chromium suite makes real requests to Flask with a restricted
PostgreSQL role in a disposable database. It covers cookie-backed login/logout,
announcement create/edit/delete persistence and role revocation. It cannot call
the privileged host API. This supplements API/unit contracts; full deployed
Apache, VM provisioning, exercise solving and target upgrade/failure/rollback
remain distinct appliance gates.
