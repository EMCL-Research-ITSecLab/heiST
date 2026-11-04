# Frontend development and releases

The student workspace and administration console use React, TypeScript and Vite.
The browser uses the unprivileged Flask REST API under `/api/`; authenticated
platform operations pass to a separate privileged API. The browser never receives
the internal authentication token. PHP is retained only as a migration reference
until the checked replacement deployment and appliance acceptance pass.

## Source layout

- `frontend/src/features/`: screens grouped by the user task they support.
- `frontend/src/components/`: accessible shared controls and display components.
- `frontend/src/lib/api.ts`: same-origin transport, CSRF, errors and downloads.
- `frontend/src/lib/state.tsx`: session lifecycle, request cancellation and actions.
- `frontend/src/lib/router.tsx`: navigation using the browser history API.
- `frontend/src/styles.css` and `tokens.css`: responsive layout and theme tokens.
- `heist/api/public/`: browser endpoints, sessions and restricted database access.
- `deploy/web/apache/heist.conf`: static serving and loopback API proxy boundary.
- `deploy/web/systemd/`: unprivileged API and image-transfer worker services.

Keep server authorization in the Flask API layer. UI route guards provide navigation
feedback; they do not grant permission. All mutations use the existing CSRF/session
checks. Never put credentials or sessions in local storage. Only theme preference
is persisted there. Resumable upload identifiers use session storage; credentials
and cookies never do. Render user content as text, and validate downloadable URLs.

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
challenge deployment. Real database/API tests and an appliance rehearsal remain
necessary; fixture tests do not establish infrastructure readiness.

Build development static assets into a separate preview directory:

```sh
python3 -m tools.frontend --development --output /tmp/heist-preview.tar.gz \
  --install-web-root /tmp/heist-preview-static
```

Development artifacts are deliberately rejected by production rollout plans.

## Release artifact

Commit reviewed source first, then build from that clean checkout:

```sh
python3 -m tools.frontend --output /mnt/data/heist-builds/releases/frontend.tar.gz
```

The standalone schema-2 archive contains the React index, hashed JS/CSS,
static presets, complete asset checksums and the full source commit. Keep it
outside Git with the matching [offline Python runtime](OFFLINE-RUNTIME.md).
The deployment host does not need Node.js or npm.

The legacy `releases/0.3.0.json` rollout adapter intentionally rejects standalone
bundles before maintenance. Do not use the former PHP-shell installation recipe
for this artifact. The new runtime adapter, restricted-role provisioning, private
media migration and fresh installer are still release gates.

The Apache template replaces incoming forwarding headers, serves static assets,
proxies only to the loopback API and denies PHP/script files. The renderer rejects
configuration injection. Its native regression runs a separate Apache process
with its own certificate, ports and document root on the disposable web VM:

```sh
HEIST_ISOLATED_WEB_TESTS=1 python3 -m tests.integration.web.proxy
```

Run that command as root on the isolated web VM with the existing Apache modules
and OpenSSL installed. It leaves installed Apache settings/services/certificates
untouched. It verifies TLS, SPA routes, static assets, API status preservation,
forwarding-header replacement, PHP denial and process cleanup. This verifies the
proxy boundary; it does not install or approve the full production migration.

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
