# Platform management

The administrator console connects exercise definitions, users, instances,
background operations and platform health. Open **Platform status** for its
Overview, Health, Jobs, Capacity, Data, Grading, Audit and Maintenance views. Running
challenges and user management remain separate navigation entries with links
from the overview. All administrator endpoints recheck the current database role;
hiding a menu item is not an authorization boundary.

Use **English / Deutsch** in the top bar to select the UI language. The choice
persists in this browser and does not reset unsaved forms. Exercise content,
commands, identifiers and reviewed legal documents retain their authored text.
Translation maintenance is described in [UI languages](../development/TRANSLATIONS.md).

## Daily operation

1. Review **Overview → Needs attention** and the global exercise readiness table.
   Follow links to the affected instances or health evidence. A ready template
   does not certify guest services or monitoring delivery.
2. Use **Running challenges** to search by exercise, user or instance ID, filter
   lifecycle states and inspect an instance. Filters and selection are in the URL
   for bookmarking and handover. Changing a filter clears the previous selection.
3. Inspect assignment, expiry, actual VM power state, configured resources,
   networks, addresses, connections and monitoring status. The network preview
   supports multiple networks, shared machines, DMZ and student-access boundaries.
4. Use **Health** for service, ingestion, archive and backup evidence. Unknown and
   stale observations require investigation; an active service alone does not
   prove that its sensor is observing the correct traffic or delivering events.

Platform operators can inspect all instances. Exercise editing, image selection
and configuration history retain author ownership checks. User management retains
its existing protections against removing the last administrator, stale role
changes and unsafe account deletion. There are no class or cohort roles.

## Instance and VM actions

Release disconnects the assignment and expires the instance for cleanup. Rebuild
removes its guest changes and creates a fresh exercise instance. Remove tears down
an eligible unassigned instance. VM controls start, gracefully shut down or reboot
only a machine belonging to the selected instance; infrastructure VMs cannot be
targeted by supplying an arbitrary ID.

Every action first requests a server preview of the assignment and affected IDs.
The confirmation sends that definition's fingerprint. The server checks it at
submission and again under the resource lease before effects. A changed owner,
assignment, machine list or network configuration invalidates the confirmation.
Grades are preserved. Rebuild is not a snapshot restore.

The HTTP response acknowledges a durable **QUEUED** job. It does not mean that the
VM operation finished. Follow **View progress** to its resource history. The
privileged `heist-administrator-worker.service` claims queued work and records
stages in the operation journal. It requires the reviewed offline runtime,
complete cleanup initialization and open maintenance admission. Its unit and
enablement are included in rollout configuration checkpoints and recovery.

| State | Operator action |
|---|---|
| QUEUED | Wait, or cancel before execution begins |
| RUNNING | Inspect stage and actual infrastructure; cancellation is unavailable |
| SUCCEEDED | The defined operation completed; verify guest service readiness separately |
| REJECTED | Read the current assignment and request a fresh preview |
| NEEDS_REVIEW | Independently reconcile VM, network, assignment and monitoring state |
| RESOLVED | An administrator recorded reconciliation; the original operation was not replayed |
| CANCELLED | No worker execution began for this request |
| UNAVAILABLE | Current journal evidence cannot be read; old successes do not certify current state |

Only one pending or uncertain queued action is allowed per assigned user or
unassigned instance. One worker owns the deployment's filesystem lease. On worker
restart, interrupted RUNNING rows become NEEDS_REVIEW. They are never replayed.
The browser's **Record reconciliation** requires recovery notes and the exact
operation ID. Do not include secrets. This acknowledges independently completed
checks; it neither retries nor undoes infrastructure changes. The same UI now
supports the current native journal operation, including `launch_challenge`,
after it enters NEEDS_REVIEW. Running operations and stale history entries
cannot be reconciled through this action. The receipt records the administrator.
`bin/heist jobs status/resolve` remains available on the host. Concurrent
multi-host queue workers are not supported by this single-Proxmox-host design.

## Grading and Moodle export

Open **Platform status → Grading**. Select an exercise, enter the student's user
ID and username, the recovered flag and a reason of 10–500 characters. Assisted
submissions use the student verifier, including personal flags and duplicate
protection. Accepted grading and administrator attribution commit in one
transaction. No flag secret is stored in the administrator audit table.

**Export submissions CSV** exports accepted submission records for the selected
exercise, or all exercises if none is selected. It includes student identifiers,
flag IDs, points, completion times and assisted-submission attribution. It does
not export flag secrets or rejected guesses.

**Export Moodle grades** requires one exercise and emits Username, Email address
and Grade (total points, deduplicated by flag). In Moodle's CSV grade import,
map Username or Email address to the matching student identifier and Grade to
the intended grade item. Set that item's maximum to the exercise total; this
export does not convert points to a different grading scale. Students with no
accepted flags are omitted, so existing Moodle grades are not overwritten with
zero. CSV spreadsheet-formula prefixes are escaped. Exports are administrator
only, rate limited and marked no-store; protect downloaded student records.

Schema migration `0016_administrator_grading` must be installed together with
the new API before using grading or exports. The rollout manifest includes it.

## Exercise configuration history

Exercise **History** records immutable definitions, image identities, resources,
network attachments, flags and hints. Creating, editing, retiring and restoring
record revisions transactionally; unchanged configurations are deduplicated.
For a legacy exercise, **Record current revision** starts history from its current
definition. Metadata history and revision detail require the exercise owner to
remain an administrator. Flag values are not rendered in the revision inspector.

**Clone as draft** creates a separate inactive exercise through the normal
validation and import path. It does not change current student instances.
Referenced image identities must still exist and be available. A revision does
not preserve OVA bytes or guest disks, and deleting an exercise removes its full
configuration snapshots. The separate metadata audit retains deletion events.
Back up the database and registered image library independently.

### Editing an existing exercise

Edit and Leaderboard open in scrollable overlays. Close or press Escape to
return to the table. Switching exercise IDs resets the complete editor,
including imported metadata, machines, networks, flags and hints. Save paused
configuration changes before using **Publish saved challenge**.

Click column headings in challenge management, exercise availability and the
artifact library to sort ascending or descending. The arrow and `aria-sort`
indicate the current direction. Challenge sorting covers all matching results
before pagination; filters and refreshes preserve the selected sort.

Use **Manage challenges → Edit** for machine resources, directory
roles, networks, flags and hints. The server permits this only while the
exercise is paused, not retired, and has no remaining assigned, provisioning or
ready instances. Set its manual pool target to zero, wait for unused copies to
drain and active labs to finish, then pause it. A fingerprint prevents saving
over another administrator's change.

Existing machine and flag identities are preserved. CPU, RAM, names, directory
roles and network membership may change, but an edit cannot add or remove a VM
or replace its OVA. Use **Clone as draft** when the machine/image set must
change. Flags that have already been earned keep their verifier, points,
student-specific setting and machine assignment. Resource edits are applied to
new clones; existing instances are never rewritten. Publish only after a fresh
inactive launch verifies boot, network topology, flag injection and grading.

## DNS in isolated exercises

An owner connecting through the VPN must be able to query the resolver on an
accessible scenario link over UDP and TCP port 53. These requests terminate on
the host (`INPUT`), so guest `FORWARD` permissions alone are insufficient.
The launch policy grants only the owner's VPN /32 address access to that link's
resolver /32; stopping the user or removing/reassigning the link revokes it.
Host management and other users' resolvers remain blocked.

If `dig @RESOLVER lab-hostname A` times out, check the VPN route and the host's
owner-specific DNS permission before changing client DNS configuration. A
successful query on the host alone does not verify the VPN-to-resolver path.

Guests use the DNS resolver on their own scenario link by default. Public DNS
fallback is no longer advertised implicitly: `.heist.test` is private, and
unreachable public resolvers can make the guest's resolver spend many seconds
failing over before an LDAP/HTTP connection even begins. A measured Lab 01
comparison reduced resolution from 13–15 seconds to 1–3 milliseconds and LDAP
bind/search from 12–20 seconds to 8–9 milliseconds when using only the local DNS.
The unassigned test instance's original settings were restored after comparison.

`CHALLENGE_DNS_FALLBACK` is an explicit comma-separated IPv4 override, empty by
default. Use it only for resolvers that are reachable from that exercise and
resolve its private names. An exercise needing external DNS requires an
intentionally configured resolver/forwarding policy; public resolvers do not
replace the authoritative exercise DNS or AD domain controller.

This default affects newly generated DHCP configurations. Existing active and
ready instances retain their configuration and leases. Updating source alone
does not repair those guests. Preserve active students' progress: check each
scenario interface and router, save current settings, update its DHCP DNS policy
and renew the appropriate lease or apply a reversible per-link resolver repair.
Exclude the dedicated monitoring NIC. Do not reset an exercise merely to repair
DNS, and do not replace dynamic addresses with static template addresses.

## Investigating launches and pool preparation

Check both workers when launches fail or the warm pool stays empty:

```sh
systemctl status backend.service pool_manager.service
journalctl -u backend.service -u pool_manager.service --since '15 minutes ago'
systemctl show backend.service pool_manager.service -p ExecStart -p DropInPaths -p BindReadOnlyPaths
```

The Git revision alone does not describe a service with versioned entry points or
read-only source mounts. Check that those scripts and their imported helpers come
from compatible revisions. In particular, the isolated DNS helper accepts an
omitted fallback argument and reads the explicit, normally empty
`CHALLENGE_DNS_FALLBACK` setting. A mismatched signature stops every preparation
before guest configuration.

Temporarily disable the affected exercise's launch readiness before investigating
a repeated failure. Preserve assigned instances. Let active Proxmox operations
and cleanup finish before restarting the pool; interrupted `PROVISIONING` rows
require reconciliation with the actual VMs, networks and operation journal.
Never mark them ready or delete database rows just to silence recovery checks.

Guest-agent sockets can appear before the guest agent starts. The client uses
its boot-wait allowance for initial synchronization, discards stale channel data,
and matches subsequent responses to request IDs. A missing execution PID is an
error, not permission to execute the command again. Only observational requests
may reconnect and retry after an ambiguous response.

After a repair, verify an actual ordinary-user launch, its countdown, a replacement
warm spare while that lab remains active, and cleanup of the operator's test
account and instance. An active worker service alone does not prove this path.

## Capacity and pool policy

**Capacity** distinguishes measured host CPU, RAM and root-filesystem usage from
configured guest allocations. Missing or impossible host measurements remain
unavailable. The root filesystem is not a complete inventory of Proxmox storage
pools. Configured vCPUs and RAM are not actual utilization measurements.

Each exercise can use forecasting with a minimum of six ready copies or an
explicit ready-copy target from 0 to 10. Saving a policy requires the last
observed revision, so concurrent administrator changes cannot silently overwrite
each other. A policy may be staged while an exercise is inactive or still being
imported; preparation starts only after it is published and import-ready. The
pool manager applies targets asynchronously. Assigned instances remain unchanged.
Displayed RAM estimates do not reserve capacity or guarantee immediate
availability. Use zero to drain unused copies before configuration work.

## Audit, privacy and maintenance

**Audit** lists exercise configuration events with actor, time, exercise and
revision IDs, including deletion metadata. It is not a complete record of every
administrator read or infrastructure action; queued actions have their own
resource histories. No raw shell output, credentials or private job payloads are
returned by these read models.

**Data** reports aggregate account preferences. Users change their default-enabled
training preference in Profile, outside signup. Dedicated training capture,
export, revocation and deletion acceptance remain unfinished; the console reports
capture and export disabled. Account eligibility alone does not authorize a
working capture pipeline. See [training data](TRAINING-DATA.md).

**Maintenance** shows the recorded release, pending requests and bounded release
transaction metadata. Maintenance mode Off means normal admission is open. The
console does not deploy code or toggle production maintenance. For acceptance
evidence, configure the private backend environment's `HEIST_DEPLOYMENT_CONFIG`
with the existing reviewed deployment JSON path. This view uses the rollout CLI's
checksum, source, configuration and sibling-receipt verifier. A verified receipt
for another commit does not certify the installed release. Missing or unreadable
evidence is explicit. A recorded checkpoint alone is not a successful restore.

Full-platform installation, upgrade, failure recovery, newer-data rollback and
reboot acceptance remain separate release gates. See [updates](UPDATES.md) and
the [test concept](../testing/TEST-CONCEPT.md). Do not deploy an unverified
candidate simply because its console renders correctly.
