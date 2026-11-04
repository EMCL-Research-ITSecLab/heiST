# Flask API and repository migration

The agreed final architecture removes PHP and the old `webserver/` source tree.
React remains in `frontend/`. Existing Flask/PostgreSQL components are retained;
no additional application framework is introduced. The public application runs
as an unprivileged service on the web VM. VM lifecycle operations remain behind
the authenticated internal service on Proxmox. An Internet-facing web request
must never directly execute privileged host code.

## Required boundaries

| Component | Responsibility |
|---|---|
| `heist/api/public/` | Browser API contracts, route authorization and response encoding |
| `heist/api/internal.py` | Authenticated internal platform API; no browser sessions |
| `heist/artifacts/` | Private resumable staging and bounded OVA envelope inspection; no privileged import |
| `heist/security/` | Password compatibility/upgrades, sessions, CSRF, authorization and rate limits |
| `heist/platform/` | Challenge, image, pool and user/VPN application services |
| `heist/infrastructure/` | Proxmox, guest, network and database adapters |
| `heist/installer/` | New-host provisioning and service installation |
| `heist/rollout/` | Versioned deployment, dependency adapters and recovery |
| `frontend/` | React source; static artifacts built on the workstation |
| `deploy/` | Reverse proxy, service, timer and configuration templates |
| `tools/` | Explicit user/administrator workstation utilities |

## Migration acceptance checklist

- Preserve and test every browser contract: session bootstrap, login/signup/
  logout/reset, dashboard, explore, challenge actions, profile/private/public,
  badges, activity, announcements, challenge authoring/management, artifacts and
  administrator diagnostics.
- Persist sessions server-side, rotate/revoke them, validate roles against the
  database and enforce CSRF/origin checks on every unsafe method.
- Retain legacy password verification while upgrading successful logins to an
  adaptive salted hash. Keep account IDs, grades and private artifacts intact.
- Port archive/OVF validation bounds and chunk-upload ownership/reconciliation;
  do not trust file extensions or extract untrusted archives into the web root.
- Preserve worker expiry/cleanup behavior; replace PHP cron with a bounded,
  observable Python service/timer. Test interruption and concurrency.
- Build a source-bound public API/runtime artifact with the existing Flask stack.
  Gunicorn is approved and pinned in `deploy/web/requirements.txt`. The
  loopback-only runner and unprivileged service template are available; the
  offline runtime bundle and rollout adapter still require verification.
- Replace Apache PHP handling with static React serving and a loopback proxy to
  the unprivileged Python service. Preserve certificate verification and limit
  forwarded-header trust to that local reverse proxy.
- Extend fresh installation and rollout adapters for the new web runtime,
  dependency changes and database migration. Older runners must reject the new
  protocol. Preserve a whole-VM rollback to the current production baseline.
- Remove obsolete PHP, Composer, views, JS/CSS, worker cron and installer paths
  only after Flask contract and appliance parity checks pass.
- Keep every supported function in the inventory and map behavior assertions to
  passing tests. Run the full catalogue and final-commit recovery rehearsal.

This checklist is tracked work, not a statement that the migration has already
passed. The current production baseline is untouched.
