# Administrator operations

The console separates exercise management from platform diagnostics. Exercise
management has search, category/availability filters, sorting and pagination;
mutations retain server-side ownership and administrator checks. Role revocation
must be tested independently of the menu state.

The platform status page reports database reachability/schema access, fixed systemd
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

## Partial imports and quarantined transfers

An exercise definition saved inactive after an import error must be inspected
before retrying provisioning. Keep its identifier and the corresponding Proxmox
task IDs. A timeout does not prove that the operation failed; do not submit a
second definition or delete its metadata to retry. Confirm machine readiness
before publishing. Retirement prevents new allocation while preserving current
students and grades. Permanent deletion requires confirmed instance teardown.

The candidate Flask artifact endpoints report `RECEIVING`, `SEALED` or
`CANCELLED`. `SEALED` means transfer complete in private quarantine, not that a
VM image is validated or ready for an exercise. The import worker and its
reconciliation controls are still being migrated. Do not manually register a
quarantined payload to bypass inspection. Unsealed transfers can be cancelled;
expired receiving sessions currently need that explicit cancellation.

The candidate cleanup service closes launch admission until it produces a
completed receipt. Preserve unresolved VM/network/monitoring records and inspect
native task results before recovery. Monitoring TLS failures require repairing
certificate trust/SAN configuration, not disabling certificate verification.

## Import an exercise from YAML

Open **Create challenge**, choose a `.yaml` or `.yml` file under **Import YAML**,
and review the populated form. Import replaces the current draft and creates no
exercise or VM. Existing `ctf` files with named `vms`, `subnets`, `flags` and
`hints` mappings are supported. Local `ova_path` fields are ignored in the browser;
upload the images first. Image names must resolve to your available artifacts.
The editor accepts an omitted `.ova` suffix when it identifies an uploaded file.

The 256-KiB import limit, bounded nesting and entry counts, safe YAML loader,
duplicate-key refusal and alias refusal apply before preview. Invalid imports
leave the current draft intact. Select **Create challenge** only after reviewing
the machines, network membership, flags, hints and availability. Creation retains
the normal owner, topology, image-readiness and partial-import checks. The existing
platform PyYAML dependency parses the file; no parser library was added to the
frontend or browser-service runtime.

## Registration and legal pages

`/impressum` and `/privacy-policy` serve the copied legal content supplied by the
operator from `https://emcl-ctf.iwr.uni-heidelberg.de`. Source URLs and response
hashes are recorded in `assets/legal-sources.json`; executable page scripts and
the old navigation were excluded. Legal text remains accessible without a working
session database. The old Font Awesome license link is preserved through a local
static license copy. Other operators must review and replace these institutional
texts and links for their own deployment.

Set `LECTURE_SIGNUP_TOKEN` in the private backend environment before deploying the
web role. The installer wizard generates a private random default and retains an
existing configured value. The code is masked in the wizard and never returned
by `/api/site` or `/api/session`. Missing codes and known placeholders keep signup
closed. `HEIST_REGISTRATION_ENABLED=false` closes signup explicitly. See
`config/registration.env.example`. Do not commit the real lecture code.

Signup requires the lecture code and an initially unchecked acceptance checkbox
for the linked Impressum and privacy policy. The API independently checks both,
including the policy version the user reviewed. Account creation and the
`registration_acceptances` audit row commit together; an acceptance write failure
rolls back the account. The audit retains the linked URLs, version and timestamp,
without retaining the lecture code. It is deleted with the account.

The default revision is bound to the bundled text. Update `HEIST_LEGAL_VERSION`
when external policy text changes; the browser must reload and review a changed
version before it can register. Apply release migration `0010` before running the
new browser service. Token rotation requires updating the private environment and
restarting/redeploying the web role. Existing users can continue signing in.

The challenge editor includes a live SVG network preview and a textual connection
list. It updates after YAML import, edits, attachment changes and removals; DMZ
and student-accessible networks are labelled. No graphing library is required.

To refresh the bundled pages, download verified HTTPS snapshots as `impressum.html`
and `privacy-policy.html`, then run
`python tools/maintenance/import_legal_pages.py --source-directory DIRECTORY`.
Review the text and provenance changes before building. This updates the text-bound
revision automatically and excludes scripts and the old navigation.
