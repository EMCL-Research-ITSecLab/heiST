# Rollout validation — 2026-10-30

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
