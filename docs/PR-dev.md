# Consolidate platform maintenance, local testing and the React workspace

Target: `main`, from `dev`. All earlier local feature and maintenance branches
are already included in `dev`; no stacked merge order is needed.

heiST previously mixed its application, installer and operator helpers, while
student and administrator screens depended on separate PHP templates and scripts.
This branch introduces one React/TypeScript workspace for both audiences and
moves core Python code under `heist/`. Image builders, challenge imports, archive
utilities and the isolated OVA runner have explicit commands under `tools/`.

The existing Flask/PostgreSQL and session-protected PHP APIs remain the runtime
boundary. The browser receives user/session/CSRF data, never infrastructure API
credentials. UI code is organized by feature, with shared transport, navigation,
request state, components and theme tokens. Unused PHP-era JS/CSS/partials are
removed; existing URLs serve the React shell.

Scheduled production updates use immutable plans, verified SQL and infrastructure
VM checkpoints, ordered migrations, protected grade checks and recovery journals.
Static UI bundles are pinned to the target commit, verified before maintenance,
and checkpointed with the release. Production requires no Node.js installation.
The new release manifest schema prevents an older runner from deploying PHP shells
without the matching built assets. Existing private configuration paths continue
to work after the package reorganization.

Validation for the current changes:

- Portable Python suite: 150 discovered, 139 passed and 11 environment skips.
  A separate appliance run passed 148 of 149 cases with PostgreSQL enabled; its
  remaining network case requires the explicit private-netns opt-in. The later
  added case checks internal import/entrypoint paths after the reorganization.
- Strict TypeScript compilation, production Vite build and eight transport tests.
- Chromium fixture tests cover routes, roles, login, forced password changes,
  structured challenge creation, chunked uploads, error recovery and mobile UI.
- 147 PHP tests / 559 assertions passed in a private web-source/vendor copy inside
  the isolated nested Proxmox fixture.
- Real browser login and 12 student/admin/public-profile screens passed against
  PHP and PostgreSQL. The temporary administrator was removed; original account
  and grade hashes were unchanged.

The earlier full update/failure recovery/rollback/reboot rehearsal applies to the
revisions recorded in `docs/ROLLOUT-VALIDATION.md`. Repeat that full rehearsal for
the final `dev` revision and its source-bound UI bundle before production rollout.
Complete challenge lifecycle tests for the rewritten UI also remain a release
gate. No production deployment or remote push is included.
