# Platform management

The administrator console connects exercise definitions, users, instances,
background operations and platform health. Open **Platform status** for its
Overview, Health, Jobs, Capacity, Data, Audit and Maintenance views. Running
challenges and user management remain separate navigation entries with links
from the overview. All administrator endpoints recheck the current database role;
hiding a menu item is not an authorization boundary.

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
checks; it neither retries nor undoes infrastructure changes. Legacy journal
operations still use `bin/heist jobs status/resolve` on the host. Concurrent
multi-host queue workers are not supported by this single-Proxmox-host design.

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

## Capacity and pool policy

**Capacity** distinguishes measured host CPU, RAM and root-filesystem usage from
configured guest allocations. Missing or impossible host measurements remain
unavailable. The root filesystem is not a complete inventory of Proxmox storage
pools. Configured vCPUs and RAM are not actual utilization measurements.

Each exercise can use its existing forecasting policy or an explicit ready-copy
target from 0 to 10. Saving a policy requires the last observed revision, so
concurrent administrator changes cannot silently overwrite each other. Nonzero
targets require a published, import-ready exercise. The pool manager applies
targets asynchronously. Assigned instances remain unchanged. Displayed RAM
estimates do not reserve capacity or guarantee immediate availability.

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
