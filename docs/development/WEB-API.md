# Browser API migration

The unprivileged Flask application lives in `heist/api/public/`. Its database
connection uses the explicitly declared restricted API role, never the Proxmox
host's PostgreSQL administrator. Platform operations travel over authenticated,
certificate-verified HTTPS through a fixed operation whitelist.

The implemented contracts include authentication/session bootstrap, learning
views, private/public profiles, avatar storage, password change, VPN download,
account removal, challenge reads/start/stop/flag submission/time extension,
administrator user/session/instance management, diagnostics, announcement administration and exercise authoring/
management, resumable artifact upload, disk validation and image publication.
React calls these Flask REST endpoints. A Python timer implements expiry and a
separate unprivileged worker handles sealed image transfers. Installation/rollout
integration and whole-appliance acceptance remain release gates; these contracts
alone do not authorize deploying the migration.

## Challenge timing

Student challenge timing reports `timing_ready: false` and
`remaining_seconds: null` while activation has not replaced the pool's placeholder
expiry with a real deadline. The browser shows preparation, disables extensions
and refreshes in place. It never substitutes a guessed one-hour deadline.
Finalized timing counts down normally and permits the full six extensions.

## Connected administrator management

All paths below require a current administrator session. Mutations also require
the existing CSRF protection. The browser never supplies its privileged actor ID;
the public API derives it from the session and forwards only allowlisted internal
operations. Restricted web-role credentials cannot read the private queue,
exercise revisions or pool policy tables directly.

| Browser endpoint | Contract |
|---|---|
| `GET /api/admin/overview` | Aggregate counts, global exercise readiness, host measurements and pool policy revisions |
| `GET /api/admin/instances` | Bounded `search`, `state`, `template_id` and `page` filters |
| `GET /api/admin/instances/<id>/preview` | Allowlisted action and optional `machine_id`; returns affected IDs and definition fingerprint |
| `POST /api/admin/instances/<id>` | Release/rebuild/remove with `action` and exact `expected` fingerprint; returns QUEUED identity |
| `POST /api/admin/instances/<id>/machines/<vm>` | Start/shutdown/reboot with the same preview contract; verifies instance membership |
| `GET /api/admin/jobs/<scope>/<resource>` | Bounded safe operation history and current receipt state |
| `POST /api/admin/jobs/<job>/cancel` | Only QUEUED work can be cancelled |
| `POST /api/admin/jobs/<job>/resolve` | Only uncertain managed work; requires `reason` and exact operation-ID `confirmation` |
| `POST /api/admin/pools/<exercise>` | `size` 0–10, boolean `enabled`, `expected_revision`; asynchronous policy application |
| `GET /api/admin/audit` | Paginated exercise-event metadata |
| `GET /api/admin/maintenance` | Release/transaction metadata, pending-work count and existing CLI acceptance verification |
| `GET, POST /api/admin/challenges/<id>/revisions` | Owner-scoped list or record-current revision |
| `GET /api/admin/challenges/<id>/revisions/<revision>` | Owner-scoped immutable definition |
| `POST /api/admin/challenges/<id>/revisions/<revision>/clone` | Validate retained image identities and create a separate inactive exercise |

The SQL queue acknowledges receipt separately from infrastructure completion.
One source-verified privileged systemd worker processes it under a singleton
lease. The operation journal preserves actor, stages and terminal outcomes;
recovery never automatically replays uncertain work. See the
[management runbook](../administration/MANAGEMENT.md) and
[acceptance concept](../testing/TEST-CONCEPT.md) for deployment boundaries.

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

Migrations `0002`–`0006` require the deployment connection to declare
`heist.web_api_role`. They refuse privileged/schema-owning web roles, remove
PUBLIC execution grants in the API schema and grant the named web role
explicit access. Schema observers cannot obtain password hashes or issue
sessions. The deployment adapter must audit the existing role and bind this
setting; the current release manifest declares the migration chain, while production admission remains gated.
Every new browser database connection also checks the actual role capabilities,
schema-creation privileges and direct account-table access. Changing the role
name cannot bypass that check. API function search paths put trusted schemas
before `pg_temp`, including the legacy stored procedures.

## Exercise authoring and retirement

The administrator authoring API validates owned images, machine/resource bounds,
flag/hint order, network reachability and Windows/AD topology before provisioning.
Definitions are saved atomically with availability disabled. Successful machine
import and confirmed readiness enable the requested availability. A transport
failure leaves the inactive definition available for inspection; the same-name
check prevents a blind retry from creating another partially imported exercise.

Management is scoped to the authenticated administrator's own exercises.
Metadata editing preserves machine and flag identities. Retirement retains grades
and lets assigned students finish; retired/inactive exercises receive no new pool
warmups. Permanent deletion is explicit, stops assigned instances, checks teardown
completion and serializes the final database removal with grading. An uncertain
infrastructure result keeps the definition retired for reconciliation.

Shared launch/warmup guards conflict with exclusive internal import/delete
requests. Provisioning rechecks availability at the privileged boundary so a
previously queued warmup cannot start a retired definition. The durable operation journal records intent before effects and blocks new
mutations after uncertain worker/task outcomes. Recovery requires independent
native-task/resource checks and an explicit local resolution; it does not replay
VM provisioning automatically.

Legacy SHA512 password hashes remain readable and are upgraded to salted
scrypt after a valid login. A forced-reset account must complete its reset
before using learning or administration routes. Invalid login responses do
not reveal whether the account exists.

## Resource cleanup and admission

Privileged VM deletion waits for the Proxmox task and confirms absence with a
successful inventory query. Inventory, stop and network-reload failures propagate;
cleanup does not unlock or forcibly destroy a VM after an uncertain response.
Instance teardown claims eligible state under an exclusive instance lease,
checks the expected exercise and preserves resource records until VM, DNS,
firewall, network and monitoring cleanup have completed. Metadata deletion and
subnet release then commit in one database transaction. DNS shutdown uses an
owned pidfd rather than signalling a potentially recycled numeric PID.

Wazuh requests now verify TLS. Existing installations need a certificate with a
matching hostname/IP SAN and either system trust or an absolute
`WAZUH_CA_CERTIFICATE_FILE` path. For an existing self-signed service without
SANs, `WAZUH_PINNED_CERTIFICATE_FILE` can trust its exact leaf copied through a
verified administration channel. This pins identity while retaining certificate
chain and expiry verification; it does not trust a certificate fetched from an
unauthenticated API connection. Missing credentials, failed TLS or an ambiguous
agent-deletion response prevent resource release. The pending deployment adapter
must configure and verify this trust before enabling the new runtime.

Startup cleanup must produce its completed receipt before launch admission and
readiness become available. Liveness and administrator reconciliation remain
accessible. An unresolved instance leaves readiness closed; the pending durable
job reconciler must handle interrupted provisioning before automatic recovery can
be claimed. File leases do not provide task recovery across worker or host crashes.

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

A separate native Proxmox test uses a diskless, NIC-less temporary VM on the
isolated test host. It checks start, stop, conversion to template, task completion,
deletion and idempotent absence; it refuses an occupied VM identifier. With an
unused identifier and a private backend environment file:

```sh
HEIST_ISOLATED_PROXMOX_TESTS=1 HEIST_TEST_VMID=990001 \
HEIST_TEST_BACKEND_ENV=/private/backend.env \
python tools/verification.py run --suite proxmox --strict \
  --output /private/new-proxmox-evidence
```

This covers physical VM operations, not OVA import, network creation, monitoring
TLS or the complete student workflow. Those remain separate appliance gates.

## Quarantined artifact intake

The new administrator-only `/api/admin/artifact-uploads` endpoints create a
server-generated upload identity, accept indexed `application/octet-stream`
chunks, report progress, cancel an unsealed transfer and seal a complete transfer.
Chunks are 4 MiB; the last chunk must have its exact remaining length. A repeated
chunk is accepted only when its bytes match. Private owner namespaces, per-upload
file leases, durable chunk receipts and atomic assembly support retries and
process restarts without accepting a different payload for an existing index.
There are at most two pending transfers per owner, each at most 16 GiB, with a
24-hour receiving window and staging-space checks. Expired transfers currently
require explicit cancellation; stale receiving transfers expire after 24 hours; the worker reclaims completed staging data.
Quota admission is per owner, not a reservation of shared storage across owners.

Sealing returns HTTP 202 and state `SEALED`, with an explicit quarantine message.
It does not insert a `disk_files` record, make the artifact selectable or contact
Proxmox. Once a transfer is sealed, cancellation is refused because later job
outcomes must be reconciled. React sends binary chunks with a session CSRF header; a stable transfer identity survives browser/worker retries.

`heist/artifacts/ova.py` inspects uncompressed USTAR/GNU regular-file envelopes
without extraction. It rejects extended/sparse headers, links, unsafe or duplicate
names, unexpected members, malformed/non-UTF-8 XML, DTD/entity declarations,
external references, mismatched file sizes and inconsistent disk declarations.
The default disk payload and declared virtual-size limits preserve the existing
16-GiB policy. Optional manifests are bounded archive members, not authenticated
signatures, and their checksums are not yet verified. Envelope inspection does
not parse VMDK content: sandboxed disk validation must independently check format,
virtual size, backing/external extents and conversion before publication. It is connected to the sealed-upload worker and privileged intake. The host
then parses VMDKs inside a separate mount/network/PID namespace without host
secrets or network access, drops privileges, enforces resource limits and converts
to standalone QCOW2. The host verifies output headers, capacity and hashes before
publication. Native Proxmox import uses those normalized disks and a BIOS/SATA
hardware profile; explicitly EFI/Secure Boot or multi-machine OVAs are rejected.
An available disk is not evidence that an exercise boots and solves correctly;
that requires the challenge acceptance rehearsal.

## Interrupted operations and expiry

Privileged start/stop/import/delete requests now write intent to a private,
fsynced operation journal before invoking infrastructure. Resource leases cover
execution. A repeated operation identity with identical input returns its recorded
success; different input with the same identity is rejected. Exceptions or worker
loss leave `NEEDS_REVIEW` (or an uncertain `RUNNING` record), blocking further
mutations for that resource. External effects are not assumed to be exactly once.
The web transport retains the same internal identity within a request; ambiguous
outcomes still require status checks rather than an automatic fresh operation.

`heist jobs status --scope user --resource ID` inspects a receipt. Local root
recovery requires platform maintenance, the exact current operation identifier
and a reason recording independent checks of native tasks/resources. Resolution
acknowledges those checks; it does not execute teardown or reconstruct a lost
result. Preserve operation journals across source updates and recovery. Browser
recovery controls and full native-task reconciliation remain integration work.

Migration `0007_monotonic_resource_ids.sql` stops recycling account, instance,
network and machine IDs, advancing sequences past existing/reclaimed high-water
marks without changing existing rows. It requires quiesced writers. Hypervisor
inventory must still be checked for foreign/orphan resource collisions; sequence
monotonicity does not certify ownership of an existing VM.

The Python expiry service checks at most 100 expired assignments per sweep and
rechecks assignment identity and expiry under row locks before removing access.
A concurrent extension or changed assignment makes the stale expiry a no-op.
Failures preserve assignments and fail the service visibly. The platform timer
replaces the PHP worker only when the deployment adapter installs it and removes
the old cron entry. Pool restart no longer converts unknown provisioning to
teardown; unresolved provisioning requires explicit reconciliation.


## Allocation history across rollback

New rollout checkpoints preserve all public sequence high-water marks in private
host state outside VM snapshots. Recovery advances restored sequences and disables
legacy resource reclaim triggers before writers resume. It also deletes restored
Flask sessions, preventing revoked sessions from returning after a database rewind.
This repairs allocation policy without rewriting student or grade rows. The host
history must be backed up and retained with the independent recovery material.
Legacy PHP sessions and registered template/image state still need complete
checkpoint integration before the full rollout is approved.


## Administrator recovery endpoints

The public API adds `GET /api/admin/jobs`, `GET /api/admin/users`, `POST /api/admin/users/<id>`,
`GET /api/admin/instances` and `GET/POST /api/admin/instances/<id>`. These require
fresh administrator authority, the usual session/CSRF checks and bounded inputs.
An actor ID supplied by the browser is ignored; the actor comes from its session.
The internal API checks that actor against the current database again.

Users can be searched/paged, promoted/demoted, assigned a temporary password, or
have browser sessions revoked. Role changes serialize with other administrator
account decisions, recheck authority after waiting, protect the last administrator
and invalidate session versions. Passwords are never journalled. The browser DB
role gains no direct account-table privileges.

Instance inspection returns bounded VM states, network prefixes, attachments,
addresses and safe operation metadata. Release uses an expected instance ID;
rebuild then removes the old instance and launches the same exercise for that
student; removal refuses assigned, reserved and provisioning instances. All writes
use resource leases and durable journal identities. Uncertain failures require
independent reconciliation. No endpoint accepts arbitrary SQL, commands, units,
file paths or a request to bypass the production maintenance gates.

The administrator guide describes the actions and recovery limits. Tests exercise
real PostgreSQL, both Flask authorization boundaries, failure journals, concurrent
role changes and the browser workflow; they do not substitute for native VM
rebuild/removal acceptance.
