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
challenge actions/grading, administrator diagnostics and announcements. It
forwards only fixed authenticated operations to the privileged platform API.
Gunicorn runs the browser API on loopback; its approved runtime dependencies
and hardened service template are supplied. Private browser data and VM
artifacts are kept outside the static frontend.

The migration also corrects unpublished exercise visibility, collective partial
solves counted as full completions, extension/elapsed-time calculations,
concurrent grading/First Blood, firewall cleanup matching similar IP addresses,
and stop/account deletion ordering. VPN revocation now verifies CRL publication
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
  database is untouched. The current full appliance suite passes without skips.
- Real Gunicorn workers are checked over HTTP for HTTPS enforcement, safe JSON
  failures and shutdown; profile/grading/administrator contracts cover ownership,
  concurrent requests, replay, expiry and failure handling.
- A separate native OpenVPN rehearsal creates a new CA and two clients in a
  fresh network namespace. It verifies selective revocation, signed CRL,
  rejected reconnect, idempotent retry and cleanup.
- React checks include strict TypeScript, transport tests, production build and
  browser fixtures. PHP tests remain a contract reference during migration.
- The verification catalogue and reviewed assertion mappings distinguish
  executed code from behavior verified by assertions. Remaining function and
  appliance coverage is an explicit release gate.

## Remaining merge/release gates

This branch is still a draft. The React transport currently uses the PHP
reference API. Exercise authoring, artifact/chunk upload and worker contracts
must finish moving to Flask before deleting `webserver/` and Composer/PHP paths.
The new Gunicorn runtime needs source-bound offline artifacts, fresh installation,
Apache configuration, media migration, release protocol/migration binding and a
whole-appliance rollback rehearsal. Existing VPN installations need a checked
maintenance migration for CRL/management/renewal configuration. Native archive
units and renewal units require their own real systemd failure/catch-up tests.

Do not describe these pending gates as production-ready. The implementation and
acceptance details are in `docs/WEB-API.md`, `docs/ARCHITECTURE-MIGRATION.md` and
`docs/TEST-CONCEPT.md`.
