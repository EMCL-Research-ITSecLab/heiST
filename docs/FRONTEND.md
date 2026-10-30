# Frontend development and releases

The student workspace and administration console use React, TypeScript and Vite.
PHP remains the session-protected web API; Flask remains the internal platform
API. The browser never receives the internal authentication token.

## Source layout

- `frontend/src/features/`: screens grouped by the user task they support.
- `frontend/src/components/`: accessible shared controls and display components.
- `frontend/src/lib/api.ts`: same-origin transport, CSRF, errors and downloads.
- `frontend/src/lib/state.tsx`: session lifecycle, request cancellation and actions.
- `frontend/src/lib/router.tsx`: navigation using the browser history API.
- `frontend/src/styles.css` and `tokens.css`: responsive layout and theme tokens.
- `webserver/html/backend/`: existing PHP endpoints and session bootstrap.
- `webserver/html/includes/uiShell.php`: PHP entry shell for the built assets.

Keep server authorization in the PHP/API layer. UI route guards provide navigation
feedback; they do not grant permission. All mutations use the existing CSRF/session
checks. Never put credentials or sessions in local storage. Only theme preference
is persisted there. Render user content as text, and validate downloadable URLs.

## Local checks

Use Node.js 24 or newer on the workstation:

```sh
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run check
npm --prefix frontend run build
python3 -m pip install playwright
python3 -m playwright install chromium
python3 tests/browser/ui_smoke.py
```

Playwright is already a dependency of the repository's end-to-end tooling. The
browser suite runs the production build with isolated API fixtures, never a live
challenge deployment. PHP/API tests and a real appliance rehearsal remain
necessary; fixture tests do not establish infrastructure readiness.

For a preview against a local PHP web root:

```sh
python3 -m tools.frontend --development --output /tmp/heist-preview.tar.gz \
  --install-web-root webserver/html
```

Development artifacts are deliberately rejected by production rollout plans.

## Release artifact

Commit reviewed source first, then build from that clean checkout:

```sh
python3 -m tools.frontend --output /mnt/data/heist-builds/releases/frontend.tar.gz
```

The archive contains content-hashed static assets, their checksums, and the full
source commit. Keep it with the cloud release artifacts, outside Git. Production
requires Python and the existing PHP stack; it does not require Node.js or npm.

Use a new release plan with `--manifest releases/0.3.0.json --ui-bundle PATH`.
The controller validates the target revision and SHA256 before maintenance,
checkpoints the artifact with the VM/SQL backups, and installs the entry manifest
last. A changed local asset stops deployment. Runtime uploads are preserved.
Rollback restores the complete web VM checkpoint, including its prior frontend.
Older release runners reject the new manifest schema before entering maintenance.

For a fresh installation, install the same source-bound bundle into the checkout's
`webserver/html` first. The installer checks its revision and asset checksums
before bootstrapping or changing the host:

```sh
python3 -m heist.ui_assets install --bundle /path/frontend.tar.gz \
  --commit "$(git rev-parse HEAD)" --web-root webserver/html
bin/install
```

## Real appliance smoke checks

Use a dedicated account on the isolated nested appliance. This command logs in
and reads the actual UI/API; it does not launch or delete exercises:

```sh
python3 tests/browser/live_smoke.py --url https://localhost:18443 \
  --username rehearsal_admin --admin --ignore-local-tls-errors
```

Enter the password at the prompt, or supply `HEIST_TEST_PASSWORD` privately.
The existing explicit lifecycle rehearsals in `tests/end-to-end/` now use the
React controls. They create, launch, stop and delete data: run them only against
disposable exercises/accounts on the isolated appliance. Their full infrastructure
lifecycle still needs a rehearsal for this UI revision.
