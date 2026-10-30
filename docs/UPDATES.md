# Scheduled maintenance updates

`bin/install` provisions a new Proxmox host. Updating an existing installation
uses `bin/heist upgrade`; it does not rerun provisioning, networking or database
initialization. No updater can guarantee recovery from untested storage, missing
backups or an unknown production baseline. Rehearse the exact release on an
isolated restored production clone before its first production rollout.

## Scope and prerequisites

Release protocol 1 updates backend source, web source and transactional PostgreSQL
migrations together on Proxmox VE 9 / Python 3.12+. It checkpoints the complete
web, database and monitoring VMs. Python/system/Composer dependency upgrades,
external disks, passthrough devices and distributed deployments need a reviewed
release adapter; the planner refuses dependency changes it cannot handle.

Use a fetched, reviewed immutable Git revision and its `releases/*.json` manifest.
The manifest declares supported starting commits, migration checksums and protected
student/grade tables. An update from an undeclared commit is refused. This declaration
records compatibility intent; the deployment's acceptance report supplies evidence.

The host needs its existing Python environment, `git`, `pvesh`, `qm`, `vzdump`,
`zstd`, `vma`, root access and a private mounted backup filesystem separate from
its installation filesystem. Reserve all three VMs' virtual disk capacities plus
16 GiB. This conservative check allows recovery space even for incompressible data.
The web VM needs its existing Composer/vendor installation, Apache, Python 3,
iptables/ip6tables and their restore commands. SSH must work non-interactively
with previously verified host keys; agent forwarding is disabled. Monitoring
checks must describe the actual installation, not assumed service names.

Copy [deployment.example.json](../config/deployment.example.json) into a private
administrator directory, replace every identity/path and review it. Credentials
remain in the existing backend `.env`, never in the deployment JSON. Match the
three VM IDs, names, SSH endpoints and users. The updater binds each SSH endpoint
to its Proxmox VM's DMI UUID. Use locally trusted installed TLS certificates;
health checks compare the exact certificate before sending authentication headers.

The installed checkout must retain Git history. A flattened OVA source directory
must first be associated with its verified source revision; do not blindly reset
or clean an installation containing private configuration or generated scripts.
The adapter recognizes only the original installer's exact generated service
wrappers and metadata. Unknown source modifications require review.

## Review and apply

Drain assigned/provisioning challenges and disable new catalog launches before
the maintenance window. Unassigned READY pool VMs may remain: the updater closes
public access, stops writers, tears down those pools through the existing backend,
and rechecks that no challenge instances or user running pointers remain.

Run the new release runner from a separate reviewed checkout, using the installed
Python environment. This keeps the running updater independent of the installation
whose Git checkout it replaces. It never fetches code itself.

```sh
cd /root/heist-release-runner
/root/heiST/.venv/bin/python -m heist upgrade plan \
  --config /root/heist-deployment.json --target REVIEWED_COMMIT \
  --manifest releases/0.2.0.json --output /root/heist-update-plan.json

# Review the immutable commits, paths, migration digests and protected tables.
/root/heiST/.venv/bin/python -m heist upgrade apply \
  --config /root/heist-deployment.json --plan /root/heist-update-plan.json

/root/heiST/.venv/bin/python -m heist upgrade status \
  --config /root/heist-deployment.json
```

Plans are bound to the deployment file's checksum. Keep the runner, plan, journal
and backup files private. The CLI logs phase transitions; detailed VM archive
verification output is stored beside each checkpoint. Private `failure-*.log`
reports in the transaction directory retain the original exception and captured
stderr, while public phase messages contain only the failure class and report path.

For an interactive administrator session, `upgrade wizard --config CONFIG --target
REVIEWED_COMMIT` displays the same immutable plan and requires the full target
commit before applying. It refuses non-interactive input; use plan/apply for CI.

## Transaction and recovery behavior

1. Preflight checks source identity, compatibility, VM identity, backup capacity,
   idle state and baseline health.
2. Quiescence records service policy, blocks public web ports over IPv4/IPv6,
   stops PHP workers/backend/pool writers and guards the prediction cron job.
   Persistent systemd guards keep writers blocked across reboots. SSH and web
   loopback probes remain available. Unrelated firewall chains are preserved.
3. Checkpointing captures a verified PostgreSQL custom-format dump, gracefully
   stops all three infrastructure VMs, verifies each compressed VMA archive and
   records its SHA256. It retains a source Git bundle and private host configuration.
4. Deployment switches backend Git HEAD and installs managed web files. Locally
   changed web source is refused. Uploads, credentials, certificates and vendor
   dependencies are preserved; managed test/mocks source files are excluded from the public document
   root. Existing Composer autoload metadata is regenerated without plugins/scripts. The legacy
   installer ran `composer update`, so its resolved `composer.lock` and vendor package
   metadata are preserved and fingerprinted as runtime dependency state. Protocol 1
   refuses dependency declarations/lock changes between source revisions; it does
   not silently reconcile an installed dependency set with a different Git lock.
5. Migrations run in one database transaction under an advisory lock. A ledger
   records each migration ID, checksum and release commit; altered migration
   history is refused. Database work is not blindly retried after transport failure.
6. Verification checks pinned HTTPS backend readiness, SQL connectivity, web login,
   declared monitoring checks, unchanged private configuration and protected data
   hashes. The commit boundary is journalled before any writer/public access resumes.
7. Services resume according to their captured policy. Public web access opens last.

Before commit, failure restores the verified original VM checkpoint and source,
checks old health/data, records recovery verification, then resumes service. A
failure before a complete checkpoint aborts without replacing VMs. Recovery
failure retains the active journal and maintenance gate. After commit or recovery
verification, resuming **never** restores older student data automatically.

```sh
# Inspect status/journal first. Resume uses the transaction's deployment config.
/root/heiST/.venv/bin/python -m heist upgrade resume \
  --config /root/heist-deployment.json
```

A process interruption before commit recovers the baseline; it does not replay
partially executed migrations. A postcommit interruption only finishes service
restoration. Keep console access available if SSH/host networking itself fails.
Host OS/network recovery remains the administrator's tested host backup process.

Proxmox task submission intent and UPID are journalled separately. If the process
loses the submission response, inspect the node task status/log and establish which
UPID belongs to that exact request. The updater will not guess or repost it:

```sh
python -m heist upgrade adopt-task --config /root/heist-deployment.json \
  --task restore-CHECKPOINT_ID-web --upid VERIFIED_UPID --confirm-request JOURNALLED_SHA256
# Only for a recorded stopped, failed restore after resolving its cause:
python -m heist upgrade retry-task --config /root/heist-deployment.json \
  --task restore-CHECKPOINT_ID-web --confirm-request JOURNALLED_SHA256
# Then use resume.
```

If no task identity can be established, keep maintenance closed and investigate
with the node's task history. Do not edit the journal to invent a successful task.

## Deliberate rollback after a successful release

Rollback reverts database contents as well as source: grades/accounts written
since the release will disappear from the restored platform. The command requires
the current release version as explicit confirmation and creates a **new complete
safety checkpoint first**, retaining that newer data for recovery. Only the currently
installed completed transaction can be rolled back.

```sh
python -m heist upgrade rollback --config /root/heist-deployment.json \
  --transaction COMPLETED_TRANSACTION_ID --confirm-version 0.2.0
```

No checkpoints are automatically deleted. Retention is an administrator decision:
keep the checkpoints needed by the current rollback policy and verified off-host
copies before removing local generations. A mounted local backup disk protects
against an update failure; it is not an off-host disaster recovery copy.

## Database-only maintenance and installer limits

`bin/heist db backup` and `bin/heist db restore --help` provide verified custom-format
dumps and a safety backup before restore. Database-only `pg_restore --clean` does
not remove arbitrary new objects absent from its archive; it is not a substitute
for the whole-VM schema rollback above. Use the shared maintenance lock and schedule
all restore work while application writers are stopped.

The fresh installer has no transactional host rollback or resume journal yet.
The former destructive uninstall script is retired. Use disposable appliance
checkpoints to rehearse installation; do not interpret the rollout mechanism as
permission to rerun installation over production.
