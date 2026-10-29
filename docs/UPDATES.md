# Installation, updates and recovery

`bin/install` provisions a clean Proxmox host. It is not an idempotent upgrade
or uninstall/rollback mechanism. Do not rerun it over the production instance.
In particular, rerunning database initialization or network setup can destroy
state or disconnect the host.

## Review a release

The new updater is deliberately scoped to backend Python code plus accompanying
tests/docs/tooling. It uses existing dependencies. It never fetches a remote
branch, upgrades OS packages or rewrites `.env` files.

```sh
# Fetch/review the intended upstream revision yourself, then:
python3 -m setup.update plan --target REVIEWED_COMMIT
```

The plan resolves an immutable target commit and lists every backend change and
every file requiring a separate migration. Schema, dependencies, setup scripts,
web assets, VPN, monitoring and service changes block automated application.
The current production main-to-pilot upgrade includes several of these and
**must take the staged migration route below**. A plan refusal is intentional.

## Backend update wizard

Only use this after the installed baseline has authenticated `/health/ready`
and the maintenance gate, and after rehearsing that exact update locally.
Disable catalog deployments, set warm pool sizes to zero and let all challenges
and their scheduled teardown finish. The updater requires zero challenge rows
and zero user running pointers; idle READY pools must also be drained.

```sh
# Use the installation's Python environment containing existing dependencies.
sudo /root/heiST/.venv/bin/python -m setup.update wizard \
  --target REVIEWED_COMMIT \
  --state /var/backups/heist/UNIQUE_UPDATE \
  --health-url https://BACKEND_CERTIFICATE_HOST:8000/health/ready \
  --ca-file /absolute/path/to/trusted-backend-ca.crt
```

Use `apply` instead of `wizard` for an already reviewed, unattended staging run.
The wizard displays its exact commit/file plan and requires the commit ID before
applying. Source and tracked worktree must be clean. It compiles both revisions,
checks idle/health, preserves reachable Git objects in a private source bundle,
journals state, gates API POST operations with `/run/heist-maintenance`, stops
workers/backend, checks idle again, replaces only planned Python files and
verifies authenticated readiness before resuming the previously active workers.
A failed update restores previous source and checks it before resuming workers.
A failed recovery leaves maintenance enabled and records
`ROLLBACK_NEEDS_OPERATOR`. It never automatically restores a database.

The first implementation installs backend files while preserving the deployment
checkout's HEAD. Review/record those installed changes in deployment history
before planning another update; a dirty tracked tree is refused. Retain the
transaction journal and bundle. If a process or host dies during installation,
use the journal and restore the old revision's listed files from the retained
Git bundle while services remain stopped. Verify readiness before resuming.
The bundle contains source, not host/VM/database backups.

This is an initial backend transaction mechanism, not a universal release
manager. It still needs real service failure/reboot rehearsal before production
use. A schema-compatible rollback also requires behavioral compatibility with
any data written by the new version; verify that in the release rehearsal.

## Main-to-new-release staged migration

1. Record the production Git commit, OS/PVE versions, running services, VM/storage
   configuration, network rules and deployment configuration. Do not publish
   configuration secrets in a PR or test report.
2. Schedule maintenance and disable new launches. Drain warm/assigned/provisioning
   instances, stop all writers and capture a PostgreSQL custom-format dump, the
   web/database/monitoring VM backups and host configuration/certificates/keys.
   Verify backup digests and available restore space.
3. Restore the complete backup to an isolated local appliance. Verify that the
   existing production revision and data work there **before** updating it.
4. Apply the reviewed migration sequence there, including the exclusive-running-
   instance migration where applicable. Resolve duplicate ownership deliberately;
   the migration refuses conflicts. Record schema version and deployment commit.
5. Test frontend/API and challenge suites, two student VPNs, grading persistence,
   cleanup, cold boot and monitoring. Exercise failure recovery by restoring the
   original backup and retesting; code checkout alone cannot undo schema changes.
6. Only after that rehearsal, apply the identical pinned sequence during production
   maintenance. Keep external console access and the restore procedure available.
   Health failure triggers the rehearsed whole-system recovery, including the
   correct database/schema and web/backend pair.

Future work: versioned migration ledger and explicit per-release upgrade plans,
a transactional web deployment adapter, authenticated whole-platform readiness,
and an installer checkpoint/resume journal. The current fresh-install script
has no automatic transactional host rollback. The local appliance checkpoint
provides a concrete installation rollback for development; physical host
recovery remains the administrator's tested backup procedure.
