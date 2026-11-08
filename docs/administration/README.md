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
[archive VM setup](LOG-ARCHIVING.md) and [release verification](../testing/TEST-CONCEPT.md).

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

## Users

Open **Users** to search by username or email, inspect active-session counts,
review the latest operation and open the user's public progress page. Results are
paginated on the server. User inspection excludes password hashes, salts, session
cookies and host credentials.

**Change role**, **Reset password** and **Sign out sessions** require typing the
username. They invalidate existing browser sessions. Temporary passwords must be
8–72 characters; the user must replace the temporary password after signing in.
The temporary secret and its hash are excluded from operation journals. Use a
second administrator for these actions on your own account. The server serializes
role changes, rechecks authority after waiting and preserves the last administrator.
These operations preserve accounts, attempts and grades; account deletion is not
part of this administrator screen.

## Running challenges and recovery

Open **Running challenges** to inspect all instance states, including unassigned
and expired instances. **Inspect** reports database assignment, actual `qm status`
results, network prefixes, DMZ/student-access settings, machine/network connections,
addresses, MACs and the latest recorded operation. Unavailable VM status is shown
explicitly. The browser receives no raw shell output or private failure reports.

| Action | Effect |
|---|---|
| Release | Disconnect the exact student assignment and expire its instance for cleanup |
| Rebuild | Release, remove the old instance and launch a fresh copy from the exercise template; guest changes are lost |
| Remove | Tear down an unassigned, unreserved READY/EXPIRED/TERMINATING instance, including VMs, networking and monitoring registrations |

All actions require confirmation, recheck server-side administrator authority and
instance identity, and preserve grades. Rebuild is a fresh exercise deployment; it
is not a restore of a student's VM snapshot. The existing teardown ownership and
resource guards still apply. A changed assignment cannot stop a different instance.

**Platform status → Recorded operations** lists journal status across users,
instances, templates, pools and artifacts, including jobs whose instance record
has already been removed. Filter by operation state and use the displayed scope,
resource and operation IDs for reconciliation. Results exclude receipt payloads,
passwords and raw failure output. The bounded scan reports truncation explicitly.

Infrastructure writes use durable operation IDs and leases. An interrupted action
is not automatically replayed. Inspect `RUNNING`, `NEEDS_REVIEW` or `UNAVAILABLE`
status before retrying. User rows retain the operation identity even when a failed
rebuild already removed its old instance. After independent VM/network/database
reconciliation, use the host's `bin/heist jobs status/resolve` with the displayed
scope, resource ID and operation ID. Record the checks in the resolution reason;
never clear a journal solely to make a button work.

The UI does not provide a general shell, secret viewer or a bypass for maintenance
and production rollout gates. Native multi-VM recovery and exact-release acceptance
remain governed by the [release test concept](../testing/TEST-CONCEPT.md).

## Multiple networks and navigation

The editor retains the `main` network model: up to ten named networks, independent
DMZ/student-access flags, and machines attached to multiple networks. A multihomed
machine can connect the student network to an internal network. YAML imports and
manual edits share this model and the live preview; server-side reachability and
AD-topology checks remain mandatory.

**Toggle navigation** opens the phone drawer or collapses the desktop sidebar.
The desktop preference persists locally. Hidden navigation is removed from keyboard
focus, and Escape closes the open navigation and returns focus to the toggle.


## Dashboard announcements

Announcements published in **Communications** also appear near the top of the
dashboard. The dashboard shows the latest three notices, with critical and
important items placed first and labelled visibly. It refreshes while the page
is open; the full text and older notices remain on **Announcements**.

Achievement icons use the original badge artwork from the database, with the
original nine emoji as compatibility fallbacks. The original illustrated avatar
is used when no personal avatar is selected; selected and uploaded avatars remain
unchanged. The repository's original `assets/social_preview/` image is retained.
