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
  metadata/subnet rollback. The live monitoring rehearsal also verifies pinned TLS and selective,
  idempotent agent removal. Sandboxed VMDK conversion and normalized disk import
  have passed on the isolated Proxmox appliance.
- React checks include strict TypeScript, transport tests, production build and
  browser fixtures. PHP source, Composer/PHPUnit paths and legacy web provisioning
  have been removed.
- The verification catalogue and reviewed assertion mappings distinguish
  executed code from behavior verified by assertions. Remaining function and
  appliance coverage is an explicit release gate.

## Remaining merge/release gates

This branch is still a draft. The React UI now calls the Flask REST API,
including resumable binary image uploads. The image worker transfers sealed
uploads to the privileged host under stable identities; publication requires
bounded envelope inspection and sandboxed disk conversion. Uncertain operations
retain their receipts and require reconciliation. Retirement checks references
and retains a recovery copy of the source image.

The new runtime has passed offline installation and unprivileged Gunicorn checks
on the isolated web VM. The privileged Gunicorn runtime also passes managed TLS,
explicit peer-identity, authentication, maintenance and bounded shutdown checks.
The static React/loopback Flask Apache template has passed a separate native
TLS/proxy test, including spoofed forwarding headers and PHP denial. Its checked deployment adapter, Apache installation/replacement,
restricted-role provisioning, private media migration and fresh installer remain
release gates. The legacy rollout protocol rejects standalone UI bundles before
maintenance. The repository now contains the React/Flask application only;
installed legacy production VMs are handled through checked migration/recovery.

Recovery now validates and restores declared host configuration files. Future
checkpoints preserve sequence high-water marks outside VM snapshots, advance
restored allocators and invalidate restored Flask sessions. Full recovery still
needs template VM/image checkpoints and legacy PHP-session invalidation, followed
by a native upgrade/failure/rollback rehearsal. Existing VPN installations need
a checked CRL/management/renewal migration; existing monitoring installations need
checked certificate trust configuration. Native archive and renewal units require
real systemd failure/catch-up tests. Every remaining function mapping must be
reviewed against passing behavior assertions, not just execution counts.

Do not describe these pending gates as production-ready. The implementation and
acceptance details are in `docs/WEB-API.md`, `docs/ARCHITECTURE-MIGRATION.md` and
`docs/TEST-CONCEPT.md`.
