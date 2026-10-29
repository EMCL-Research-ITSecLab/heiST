# Add local appliance testing and a guarded backend update workflow

Depends on `feat/configurable-pilot-resources`; target that branch for a stacked
PR, or merge its deployment fixes first.

heiST lacked a safe, repeatable local test entry point and a separate update
path. This change adds full OVA import/run/export and verified stopped-disk
checkpoint/restore tooling, Python/API and PHP test commands, and CI using the
platform's existing dependencies. No additional application framework is added.

The internal Flask API is now a testable application factory with lazy service
boundaries, validated positive identifiers, bounded request bodies, private
errors, authenticated liveness/readiness and a maintenance gate. Existing
successful route payloads are preserved; malformed input now returns HTTP 400.

The initial update wizard handles backend-only code releases. It reviews pinned
Git revisions, refuses schema/dependency/infrastructure/web migrations, drains
checks, journals changes, retains a Git recovery bundle and rolls back failed
readiness before resuming workers. The installer remains a clean-host installer;
main-to-new-release migrations require the documented full backup/restore route.

The PHP suite separates container-backed tests, fixes obsolete upload/signup
fixtures, uses stubs appropriately, and fails on warnings/deprecations. Signup
now commits inside its error handling before authenticating a session. Logout
handles absent SameSite cookie settings and activity rendering tolerates invalid
dates. Tests reused through a vendor symlink resolve the review source correctly.

Validation: 77 Python/API/backend tests passed in the disposable appliance with
PostgreSQL and privileged firewall coverage; 142 isolated PHP tests passed with
540 assertions and zero warnings/deprecations/notices. Real QCOW2 checkpoint and
restore passed. See `docs/LOCAL-VALIDATION.md` for exact scope and the observed
nested SATA failure under concurrent bulk I/O. Full PHP database/Playwright,
capacity and production upgrade/recovery acceptance remain open. Nothing was
rolled out to production.
