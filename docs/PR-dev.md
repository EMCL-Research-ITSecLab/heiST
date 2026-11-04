# Reorganize platform services and build the Flask browser API

Target: `main`, from local `dev`. PRs #42 and #43 and the earlier local feature
branches are already included. This is a combined migration branch; no stacked
merge order is required.

The React/TypeScript workspace replaces separate student and administrator PHP
views. Python application services, infrastructure adapters, API boundaries,
installer and release tooling now live under `heist/`. Workstation image
builders, appliance testing and maintenance helpers have explicit entry points
under `tools/`; deployment templates live under `deploy/`.

The new unprivileged Flask browser API implements persistent sessions, CSRF,
current-role checks, legacy password upgrades, learning views, profiles,
challenge actions/grading, exercise authoring/management, administrator diagnostics
and announcements. It
forwards only fixed authenticated operations to the privileged platform API.
Gunicorn runs the browser API on loopback; its approved runtime dependencies
and hardened service template are supplied. Private browser data and VM
artifacts are kept outside the static frontend.

The migration also corrects unpublished exercise visibility, collective partial
solves counted as full completions, extension/elapsed-time calculations,
concurrent grading/First Blood, firewall cleanup matching similar IP addresses,
and stop/account deletion ordering. Privileged resource deletion now confirms
Proxmox task completion and absence before releasing metadata. Instance cleanup
retains its records on physical-resource or monitoring failure, uses owned pidfds
for DNS shutdown and releases subnet/database records in one transaction. VPN revocation now verifies CRL publication
and selective client disconnection before releasing account resources. A daily
persistent timer renews the CRL under the same CA lock.

Scheduled platform updates retain verified database/VM checkpoints, protected
account/grade checks and recovery journals. Frontend bundles are bound to their
source commit. Administrator diagnostics include lifecycle, service, release,
storage and a sanitized receipt from the separate archive VM. Archive services
and native journal forwarding have dedicated deployment templates.

## Validation

- Python browser contracts run against new disposable PostgreSQL databases with
  a restricted API role and a separate observer role; the installed application
  database is untouched. The Python suite passes without skips inside the
  isolated appliance; this does not replace the pending full UI/VM lifecycle gate.
- Real Gunicorn workers are checked over HTTP for HTTPS enforcement, safe JSON
  failures and shutdown; profile/grading/administrator contracts cover ownership,
  concurrent requests, replay, expiry and failure handling.
- A separate native OpenVPN rehearsal creates a new CA and two clients in a
  fresh network namespace. It verifies selective revocation, signed CRL,
  rejected reconnect, idempotent retry and cleanup.
- A native Proxmox rehearsal creates a separate diskless, NIC-less temporary VM
  and verifies actual start/stop/template/delete tasks and confirmed absence.
  Database tests cover teardown eligibility, orphan network discovery and atomic
  metadata/subnet rollback. Monitoring adapter tests cover verified TLS and
  ambiguous deletion failures; a live Wazuh TLS gate remains pending.
- React checks include strict TypeScript, transport tests, production build and
  browser fixtures. PHP tests remain a contract reference during migration.
- The verification catalogue and reviewed assertion mappings distinguish
  executed code from behavior verified by assertions. Remaining function and
  appliance coverage is an explicit release gate.

## Remaining merge/release gates

This branch is still a draft. The React transport currently uses the PHP
reference API. Chunk intake now stages and seals owner-isolated transfers in quarantine.
Disk validation/import and worker contracts must finish moving to Flask before deleting `webserver/` and Composer/PHP paths. Authoring contracts
are tested with real PostgreSQL; actual machine import remains an appliance gate.
The new Gunicorn runtime needs source-bound offline artifacts, fresh installation,
Apache configuration, media migration, release protocol/migration binding and a
whole-appliance rollback rehearsal. Existing VPN installations need a checked
maintenance migration for CRL/management/renewal configuration. Existing Wazuh certificates require checked trust/SAN migration. Startup cleanup
must complete before launch admission. Native archive
units and renewal units require their own real systemd failure/catch-up tests.

Do not describe these pending gates as production-ready. The implementation and
acceptance details are in `docs/WEB-API.md`, `docs/ARCHITECTURE-MIGRATION.md` and
`docs/TEST-CONCEPT.md`.
