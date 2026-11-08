# Rollout validation

## Flask candidate rehearsal — 2026-11-08

The original rehearsal did not contact production. The later read-only inspection
and explicitly approved backup work are recorded below. The fresh installer and production
protocol 3 upgrade gates remain closed. The checks in this dated section used code candidate
`0512fac847489457c81e54839df67aa3791d518c`. Later application changes have separate
source-bound suite evidence; this record does not certify those later changes.

| Check | Result |
|---|---|
| Clean source-bound Python suite on the isolated pilot | 427 passed, zero skips/failures; real disposable PostgreSQL and privileged namespace prerequisites enabled |
| TypeScript and frontend unit suite | Passed; 12 unit tests |
| Chromium fixture browser suite | 23 passed; 120 page/size/theme layout combinations, enrollment, YAML import and live topology |
| Real browser / HTTPS / Flask / restricted PostgreSQL | 4 passed, including lecture-code refusal and transactional policy acceptance |
| Documentation | 20 source-bound screenshots; preview now fits narrow cards without clipping machines |
| Legacy SQL migration rehearsal at `9bf3ac6` | All ten migrations, SQL/role rollback after injected failure, session behavior, role replacement and scratch-database restoration passed |
| Native whole-platform staging at `65f784b` | Target deployment, all ten migrations and target verification passed before the deliberate precommit failure |
| Recovery of that staging transaction | Initial recovery interrupted by a signer timeout; explicit journal resume completed all nine VM restores, eight source images and original source/configuration |
| Independent recovery postcheck | Three running core VM identities, six stopped template identities, original SQL counts and protected student/grade hashes matched; maintenance cleared |

The native staging transaction was `20261107T183530Z-a0f4ae4607df`. It reused the
explicit complete recovered disposable baseline after verifying protected data,
host configuration, template identities and every archive. It never committed or
opened the candidate. Its original frozen runner signed a new PVE ticket for every
status poll; a 15-second signer timeout interrupted monitoring-VM recovery.
Maintenance stayed closed. A fresh process resumed the recorded task identities;
no restore was blindly resubmitted.

This is **a recovered interruption, not a clean whole-platform rehearsal**. The
journal retains both the planned verification fault and the unexpected timeout.
The local adapter now reuses tickets in memory for five minutes and bounds signer
execution to 60 seconds. Regression tests verify refresh expiry/failure and that
polling recovery uses GET on the original task without another POST. A pinned,
read-only native PVE inventory check passed with that adapter. The complete native
staging/fault rehearsal has not yet been rerun with this fix or the compact preview.

The independent postcheck found three users, two challenge templates, six machine
templates, eight disk-file records and zero allocated challenges, with protected
student/grade hashes unchanged. Temporary database tests use separate databases
and roles; they do not migrate the original application database.

A clean full rehearsal of the exact final release, fresh-host Flask provisioning
and installer recovery, committed upgrade/rollback with newer student data, reboot
faults, VPN/PKI and archive/renewal acceptance remain required. This disposable
legacy fixture is not a restored clone of the current production installation.
Only Chromium ran locally; Firefox/WebKit and a full accessibility review remain
separate checks.

## Production preparation — 2026-11-08

Read-only inspection found a different starting revision from the legacy pilot:
`lecture_v2` at `e9dc593f71fbcb80e83cbd0cc34493739177ad46`, with ten tracked
local modifications. This revision is not declared supported by the release.
Do not discard its customizations or add it to the allowlist on the strength of
a database-only test. Production deployment remains unapproved.

The operator explicitly approved online, backup-only VM exports and a narrowly
scoped recovery export of the application's environment and backend TLS files.
Archives stream to private off-host storage. These online VM backups and the
separate logical dump are not a coordinated maintenance checkpoint. Compression
verification alone does not prove a bootable restore.

A PostgreSQL-16-produced logical dump was restored into a new scratch database on
the isolation-verified pilot. The audit runner at
`624032aba47a1b051962d8e359196f3eb3f0fed4` passed all ten real migrations,
injected migration failure, protected row/schema/role preservation, restricted
browser-role checks, later-release session invalidation and complete scratch
recovery. The original application database was not migrated. Its receipt marks
`starting_commit_declared_supported: false` and
`whole_platform_upgrade_approved: false`.

Source review also found production fixes for stale pool database connections
and an email-based personalized flag grader. The candidate now opens and closes
connections for each pool cycle and checks personalized flags against the
installed SQL grader before writing them. It preserves either email or unique-ID
grading without rewriting existing protected data. Production admission remains
closed until these changes and the remaining customizations pass clone acceptance.

Off-host receipt: `database-isolated-audit-receipt.json`, alongside the private
backup manifest. Production source/customization review, full VM restore, fresh
installation and clean complete upgrade/failure/rollback acceptance remain open.
No production services or installed application configuration were changed.

## Earlier legacy-target validation — 2026-10-30

The local release mechanism passed update and recovery rehearsals. This is not
production acceptance: production has not been contacted or changed. The fixture
uses a disposable overlay of the existing appliance, three infrastructure VMs and
synthetic accounts. Its backend source was associated with upstream main; its
already-provisioned database/platform came from the earlier pilot. It is not a
restored copy of the current production installation.

## Source and environment

- Starting backend source: `1bf6c026a9c6ce9ff6e00de9453496779c0e8043` (`0.1.0`).
- Successfully deployed application: `cd7103c5ed0dcabff6455cec211d12fb8742755c` (`0.2.0`).
- PVE 9, Python 3.12, web/database/monitoring VMs with 64-GiB virtual disks each.
- Separate 512-GiB sparse backup volume; private data under
  `/mnt/data/heist-builds/runs/rollout-validation`.
- Actual QEMU `restrict=on` profile and sampled outbound TCP denials verified for
  the running boot. The sealed upload OVA and original backing appliance were
  not replaced by the review source.

## Results

| Check | Evidence |
|---|---|
| Python/API/backend/release/appliance suite | **132 passed, zero skips** inside the fixture |
| PostgreSQL migrations | Real disposable database: idempotence, checksum drift refusal, failing later SQL rolls back earlier DDL/ledger |
| Ownership/concurrency tests | Real disposable PostgreSQL database; private objects removed |
| Privileged network regression | Explicitly enabled inside its private namespace |
| Frontend | **142 tests, 540 assertions**; warnings/deprecations fail; no database/container tests claimed |
| Frontend isolation | Private source/vendor copy removed afterwards; public lock/vendor fingerprints unchanged |
| Successful complete update | All three VMA archives verified; backend/web deployed, migrations applied, health/data checks passed; `COMPLETE` |
| Actual precommit deployment failure | All three infrastructure VMs and original source restored; old health/account/grade hashes verified before reopening |
| Deliberate rollback | A new complete safety checkpoint was created; original VMs/database/source restored; `COMPLETE` |
| Postcommit interruption/resume | Injected failure after durable commit; fresh CLI process resumed without changing restore tasks or overwriting a postcommit SQL probe |
| Web VM reboot under maintenance | Real peer TCP/443 blocked, loopback login and SSH worked before/after reboot; public access restored afterwards; protected data unchanged |
| Newer safety backup | Restored into a separate test database; newer probe and protected student/grade hashes matched |
| Cleanup | No pending transaction, temporary test database or rehearsal schema; **63 grade records** retained |

The update took **17m 34s**, including its checkpoint. Deliberate rollback and
interrupted service completion took **23m 26s**. Each full checkpoint compressed
to about **11.9 GiB**. These are measurements from this nested fixture, not a
production capacity or maintenance-time guarantee.

## Findings fixed during rehearsal

The initial PVE CLI backup call waited for its worker and timed out without
returning a task identity. Maintenance stayed closed. The exact task was located
in node history and adopted rather than reposted. Dispatch now uses the pinned
local HTTPS API and root's installed short-lived ticket signer; a username
quoting regression has explicit coverage.

The first complete checkpoint then exposed a web baseline mismatch. The restored
comparison identified only `composer.lock`: the former installer ran `composer
update`. The updater now preserves/fingerprints the resolved installed lock and
vendor metadata rather than silently replacing their dependency state.

The successful update also removed **37 exact legacy generated wrappers**, keeping
their bytes in the private checkpoint for rollback. Unknown local commands are
preserved; collisions with new maintained source are refused before maintenance.

## Reproducing destructive checks

These scripts require root on the explicitly opted-in `heist-pilot`, its private
workstation-issued isolation proof, and a proof matching the current boot. They
refuse an unverified host. Run only on the disposable fixture:

```sh
HEIST_PRIVILEGED_TESTS=1 /root/heiST/.venv/bin/python \
  tools/local/rehearse_recovery.py --config /root/rollout-deployment.json \
  --transaction CURRENT_COMPLETED_UPGRADE --confirm-version 0.2.0

HEIST_PRIVILEGED_TESTS=1 /root/heiST/.venv/bin/python \
  tools/local/rehearse_web_guard.py --config /root/rollout-deployment.json
```

The recovery script deliberately leaves the fixture on its original version.
It inserts isolated SQL probes, verifies postcommit resume in a fresh process,
restores the newer SQL dump into a separate database, and cleans up its probes.
A pending failed recovery retains its probe for diagnosis.

## Required before production

Restore a real production backup into an isolated clone and rehearse the exact
pinned release and recovery there. Verify its actual starting commit, PVE/Python
versions, dependency set, storage, custom source and monitoring configuration.
Protocol 1 supports PVE 9 and declared starting commits; it deliberately refuses
unsupported dependency/infrastructure migrations.

Repeat login/launch/solve/grade/teardown, two-student isolation, monitoring, capacity
and realistic storage-load checks against that clone. Full PHP database/Playwright
coverage, destructive host power loss at critical boundaries and a whole-appliance
migration-failure injection remain separate acceptance work. SQL failure itself
was tested in a disposable database; actual whole-VM recovery was exercised after
a deployment failure. Host OS/network rollback and a fresh-installer resume journal
are outside this release controller. Existing dependency/security modernization
also needs its own reviewed release; this change introduces no new dependencies.

The older results in `LOCAL-VALIDATION.md` belong to the parent branch and the
sealed upload appliance. They do not certify this release for production.
