# Administrator operations

The console separates exercise management from platform diagnostics. Exercise
management has search, category/availability filters, sorting and pagination;
mutations retain server-side ownership and administrator checks. Role revocation
must be tested independently of the menu state.

The lab overview reports database reachability/schema access, fixed systemd
service states, instance lifecycle counts, host root-filesystem capacity,
maintenance state, running source version, last recorded release and the separate
archive VM receipt. These are observations, not a production-readiness certificate.
Unknown, missing, failed and stale data remain visible. Downloaded diagnostics
contain no credentials, raw SSH output, student records or checkpoint paths.

| Observation | Operator action |
|---|---|
| Database unavailable | Inspect DB unit, connectivity/TLS/role grants and migration state; preserve errors before retrying |
| Backend/pool/cleanup unit failed | Inspect the named unit's journal and recent release; identify active provisioning before restart |
| Active maintenance transaction | Use `bin/heist upgrade status` with the reviewed deployment file; resume/reconcile the existing transaction |
| Archive stale/failed/unavailable | Check the archive VM timer, service result, mount, free space, SSH trust and latest receipt |
| Low root capacity | Identify growth and reserve sufficient independent backup/archive storage; never delete an active checkpoint |
| Instances stuck in a lifecycle | Reconcile the owning job/Proxmox task and owner; preserve data before cleanup; verify student isolation afterwards |

The browser does not execute shell commands or initiate production rollback.
Update, rollback and destructive recovery use the reviewed CLI/runbooks and the
scheduled maintenance window. See [updates](UPDATES.md),
[archive VM setup](LOG-ARCHIVING.md) and [release verification](TEST-CONCEPT.md).

The final architecture is being migrated from PHP to the existing Flask stack.
Do not remove the old web runtime from an installed appliance until the exact
Flask replacement and deployment adapter pass the PHP-removal, authentication,
file-validation, worker and recovery cases in the catalogue.
