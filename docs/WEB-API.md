# Browser API migration

The unprivileged Flask application lives in `heist/api/public/`. Its database
connection uses the explicitly declared restricted API role, never the Proxmox
host's PostgreSQL administrator. Platform operations travel over authenticated,
certificate-verified HTTPS through a fixed operation whitelist.

The implemented contracts include authentication/session bootstrap, learning
views, private/public profiles, avatar storage, password change, VPN download,
account removal, challenge reads/start/stop/flag submission/time extension,
administrator diagnostics and announcement administration. Exercise authoring,
artifact upload, expiry reconciliation and installation/rollout integration
remain migration work. The React transport still uses the PHP reference until
all contracts and the new appliance runtime have passed acceptance. This is
not a release approval or an instruction to deploy the partial migration.

## Sessions and database boundaries

`WEB_SESSION_SECRET` is a persistent 32-byte secret encoded as 64 hexadecimal
characters. A random opaque session identifier is stored in a Secure,
HttpOnly, SameSite=Strict `__Host-heist_session` cookie. PostgreSQL stores its
SHA256 digest. Session-bound HMAC CSRF tokens and origin checks protect unsafe
requests. Idle expiry is one hour; absolute expiry is eight hours. Login and
password change rotate sessions; logout and password change revoke old cookies.
Roles and password-reset requirements are checked from current database state.

Each authenticated mutation acquires a per-account PostgreSQL session lock;
closing the request connection releases it, including after an exception or
worker exit. Concurrent account operations receive 409. Grading has a separate
transaction-scoped challenge lock so simultaneous final flags from different
students cannot both earn First Blood. Password/session issuance and account
removal also synchronize their authentication version. Infrastructure requests
are never made while holding a `users` row lock in the web process.

Migrations `0002`–`0005` require the deployment connection to declare
`heist.web_api_role`. They refuse privileged/schema-owning web roles, remove
PUBLIC execution grants in the API schema and grant the named web role
explicit access. Schema observers cannot obtain password hashes or issue
sessions. The deployment adapter must audit the existing role and bind this
setting; the current release manifest does not yet enable these migrations.

Legacy SHA512 password hashes remain readable and are upgraded to salted
scrypt after a valid login. A forced-reset account must complete its reset
before using learning or administration routes. Invalid login responses do
not reveal whether the account exists.

## Gunicorn candidate runtime

Gunicorn is approved and pinned with the public role's existing dependencies in
`deploy/web/requirements.txt`. `python -m heist.api.serve` / `heist web` run two
threaded workers on `127.0.0.1:8001`; `HEIST_WEB_PORT` can select another
unprivileged loopback port. Request logs omit browser query strings and cookies.
`deploy/web/systemd/heist-web.service` uses a dedicated `heist-web` user,
private writable state and service hardening. The referenced versioned runtime
under `/opt/heist-web/current/` must be created by the pending deployment adapter.

Apache must serve the static React bundle, proxy `/api/` to this loopback socket
and replace forwarded-protocol/address headers. The app trusts exactly that
local proxy; the Gunicorn listener must remain inaccessible remotely. Browser
requests require HTTPS, including public image requests. A production offline
wheel bundle, service installation, Apache replacement, media migration,
health probes and whole-VM rollback rehearsal are still required before release.

## Account and VPN deletion

Deleting an account first checks the password, ownership of exercises/images
and the last-administrator rule. It stops an active lab, asks the privileged
VPN service to revoke/disconnect the client and only then atomically deletes
account data and releases the reserved IP. A failed revocation keeps the
account and IP for a retry. Instructor resources must be transferred or removed
first so account deletion cannot cascade into other students' exercise grades.
Announcements survive account deletion and follow author username changes.

VPN generation and removal share a bounded CA lock. Profiles are published
atomically with mode 0600; a partial generation retains its reusable certificate
instead of revoking another request's keys. The client certificate common name
is forced to the numeric account identifier, independent of inherited CA setup
variables. New profiles require server certificate authentication.

Removal requires `crl-verify /etc/openvpn/crl.pem`, a root-only UNIX management
socket and `management-client-user root` in the server configuration. It verifies
and publishes a freshly signed CRL before disconnecting the specific client,
checks that the client is absent, then removes leaf files. CA/revocation history
is retained. Failure at any step propagates. Fresh provisioning writes these
settings; existing deployments require a checked maintenance migration before
account deletion is enabled. A daily persistent `heist-vpn-crl-refresh.timer`
refreshes CRL expiry under the same CA lock; the signed prior CRL remains in
place if generation or signature verification fails. Fresh provisioning installs
the timer. Existing-deployment migration and a real systemd sandbox/catch-up
rehearsal remain part of the final release gate.

The management protocol follows the upstream
[OpenVPN management interface](https://openvpn.net/community-docs/management-interface/).
It never exposes a general management TCP port through the browser API.

## Verification

`python tools/check.py` includes real PostgreSQL browser contracts when
`TEST_DATABASE_URL` points to an isolated administrator connection. Each test
class creates and removes its own database, restricted API role and observer
role. Never point this at production. The suite covers CSRF/cookie replay,
forced reset, role revocation, visibility, profile privacy, uploads, grading
races, user-specific flags, timing, firewall isolation and safe failures.

The separate live VPN test creates a new CA, loopback listener and two clients
inside a fresh Linux network namespace. It verifies handshakes, signed CRL,
selective disconnection, rejected reconnect, retry and cleanup. Existing VPN
configuration and CA files are unused. On a disposable host with existing
OpenVPN, Easy-RSA and a TUN device:

```sh
HEIST_ISOLATED_NETWORK_TESTS=1 python tools/verification.py run \
  --suite vpn --strict --output /private/new-vpn-evidence
```

Run this command as root. The runner uses `unshare --net`; missing permissions
or prerequisites fail instead of being treated as passing coverage. Retain
source-bound evidence from a clean final commit for release acceptance.
