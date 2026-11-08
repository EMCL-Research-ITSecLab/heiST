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
The populated-state suite checks 220 page/size/theme combinations: twenty-two pages at
320, 390, 768, 1024 and 1440 CSS pixels, in light and dark themes. Assertions cover
horizontal overflow, one page heading, runtime errors, loaded visible images,
official branding and plain headings, YAML preview/draft preservation, retired exercise restoration, paging/filter reset, dialog cancellation and focus,
mobile keyboard navigation, theme persistence and enabled-button text contrast. CI also runs
`python tools/testing/screenshots.py --check` to reject stale documentation images.
These checks catch specified regressions; they are not a complete accessibility
audit or a guarantee that every design is attractive. Review the gallery at actual
size, including long text, empty, loading, error and destructive-confirmation states.

## Screenshot gallery

[Open the complete gallery](../../assets/screenshots/README.md): 52 full-page
captures cover every canonical view in both themes, plus phone navigation,
collapsed desktop navigation and expanded instance diagnostics. Achievements shows
all nine synthetic badges. Editor captures contain multiple networks and include
the complete machines, networks, flags and hints sections below the fold.

The generated manifest records routes, role/state, viewport, full document height,
browser version, source hashes and PNG checksums. The checker rejects missing
routes, missing theme variants, truncated images and stale inputs. Aliases share a
canonical capture. Images load before capture, including images below the fold.

All records are synthetic. These captures validate the fixture UI, not a running
Proxmox deployment. Do not retouch PNGs manually; regenerate with the command above.

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

It verifies administrator role/password changes through both Flask authorization
boundaries using an in-process internal WSGI transport and real SQL. Privileged VM
calls remain forbidden; this does not claim production internal TLS/VM acceptance.
It also verifies secure persistent login/logout cookies, actual announcement
create/edit/delete persistence and administrator role revocation. CI runs this
suite against its disposable PostgreSQL service. Preserve database credentials
in the environment rather than command-line arguments or logs.

## Native web-role rehearsal

`tools/local/rehearse_browser_guest.py` runs only on the opted-in, isolation-verified
`heist-pilot`. It requires a completed, recovered baseline checkpoint, matching
protected-data hashes, the original web VM ID, and source-bound runtime/UI bundles.
It uses a separate disposable PostgreSQL database. The native guest installs the
real Apache configuration and systemd Gunicorn service behind maintenance, probes
its SPA and liveness API through pinned Apache HTTPS, verifies public session
rejection during maintenance and session storage as the restricted service UID, kills the service main process to check systemd recovery, then
restores and verifies the original complete web VM archive. Failed recovery leaves
a private `RECOVERY_REQUIRED` journal; do not reopen access manually.

This is web-role acceptance only. It does not exercise a complete target platform
upgrade, target monitoring/VPN integration, fresh-host provisioning, or the full
upgrade/rollback fault matrix. The production installer and protocol 3 gates remain
closed. Run the workstation offline verifier immediately before this rehearsal.

The native runner may select an already fetched application `--target-commit`
independently of its own revision; the journal records both. Artifacts and service
templates remain bound to that application revision. Session checks never remove
maintenance markers or open the public firewall.
