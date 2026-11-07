# UI verification and documentation captures

Browser tests use the production Vite build served on loopback and isolated API
fixtures. They do not contact the installed platform or launch exercise VMs.
Backend contracts and actual appliance acceptance are separate release gates.

```sh
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run check
npm --prefix frontend run build
python tests/browser/ui_smoke.py
python tests/browser/ui_layout.py
python tools/testing/screenshots.py
```

Use the existing Playwright Python environment and browser cache. `HEIST_BROWSER`
selects Chromium, Firefox or WebKit for the regression suites; the CI matrix runs
all three. Documentation captures use the selected installed engine. No new
frontend testing library is required.

The smoke suite checks public/student/admin routing, CSRF login, password reset,
role boundaries, safe error recovery, authoring, binary uploads and diagnostics.
The populated-state suite checks 90 page/size/theme combinations: nine pages at
320, 390, 768, 1024 and 1440 CSS pixels, in light and dark themes. Assertions cover
horizontal overflow, one page heading, runtime errors, loaded visible images,
official branding and plain headings, YAML preview/draft preservation, retired exercise restoration, paging/filter reset, dialog cancellation and focus,
mobile keyboard navigation, theme persistence and enabled-button text contrast. CI also runs
`python tools/testing/screenshots.py --check` to reject stale documentation images.
These checks catch specified regressions; they are not a complete accessibility
audit or a guarantee that every design is attractive. Review the gallery at actual
size, including long text, empty, loading, error and destructive-confirmation states.

## Screenshot gallery

All records are synthetic. The generator uses the built application and the same
fixture harness as the regressions. `assets/showcase/manifest.json` records source
file hashes, browser version, routes, roles, viewports, themes and PNG checksums.
Regenerate after changing the UI or fixtures; do not manually retouch screenshots.

| View | Light | Dark |
|---|---|---|
| Student overview | [Light](../assets/showcase/dashboard_light.png) | [Dark](../assets/showcase/dashboard_dark.png) |
| Investigation | [Light](../assets/showcase/deploy_challenge_light.png) | [Dark](../assets/showcase/deploy_challenge_dark.png) |
| Exercise management | [Light](../assets/showcase/manage_challenges_light.png) | [Dark](../assets/showcase/manage_challenges_dark.png) |
| Exercise editor | [Light](../assets/showcase/create_challenge_light.png) | [Dark](../assets/showcase/create_challenge_dark.png) |
| Platform diagnostics | [Light](../assets/showcase/operations_light.png) | [Dark](../assets/showcase/operations_dark.png) |
| Sign in | [Light](../assets/showcase/login_light.png) | [Dark](../assets/showcase/login_dark.png) |
| Mobile overview | [Light](../assets/showcase/mobile_light.png) | [Dark](../assets/showcase/mobile_dark.png) |

The previous installer and YAML-browser screenshots were removed because those
screens are not provided by this branch. Deployment remains gated as documented in
[UPDATES.md](UPDATES.md).


## Browser with the real Flask API and PostgreSQL

`tests/browser/ui_database.py` serves the built React application and real Flask
API over loopback HTTPS. It uses the existing isolated PostgreSQL fixture to
create/drop a new database and restricted roles. Chromium trusts only the
fixture's generated certificate public key. Requests are not intercepted, and
privileged host API calls are forbidden. This is a functional UI/API/SQL test,
not a production Apache or whole-appliance deployment test.

With an isolated administrator `TEST_DATABASE_URL` already configured, run:

```sh
HEIST_BROWSER_DATABASE_TESTS=1 python tests/browser/ui_database.py
```

It verifies secure persistent login/logout cookies, actual announcement
create/edit/delete persistence and administrator role revocation. CI runs this
suite against its disposable PostgreSQL service. Preserve database credentials
in the environment rather than command-line arguments or logs.

## Native web-role rehearsal

`tools/local/rehearse_browser_guest.py` runs only on the opted-in, isolation-verified
`heist-pilot`. It requires a completed, recovered baseline checkpoint, matching
protected-data hashes, the original web VM ID, and source-bound runtime/UI bundles.
It uses a separate disposable PostgreSQL database. The native guest installs the
real Apache configuration and systemd Gunicorn service behind maintenance, probes
its SPA and session API through pinned Apache HTTPS, checks secure cookies, kills the service main process to check systemd recovery, then
restores and verifies the original complete web VM archive. Failed recovery leaves
a private `RECOVERY_REQUIRED` journal; do not reopen access manually.

This is web-role acceptance only. It does not exercise a complete target platform
upgrade, target monitoring/VPN integration, fresh-host provisioning, or the full
upgrade/rollback fault matrix. The production installer and protocol 3 gates remain
closed. Run the workstation offline verifier immediately before this rehearsal.
