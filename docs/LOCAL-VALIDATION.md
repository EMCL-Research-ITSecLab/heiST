# Local validation — 2026-10-29

Historical parent-branch record. See [current rollout validation](ROLLOUT-VALIDATION.md) and [update workflow](UPDATES.md) for the maintenance branch.

This branch was exercised on silverstone and the disposable nested Proxmox
appliance. The installed platform and the sealed revision-2 OVA were not replaced
by the review source; Python tests ran in a separate guest checkout and PHP tests
in a private web-VM source copy using the existing vendor cache.

| Check | Result |
|---|---|
| Python/API/backend/appliance/update suite in disposable appliance | **77 passed, zero skips** |
| PostgreSQL ownership/concurrency/migration tests | All seven included in the 77 passing tests; private schemas removed |
| Privileged firewall replace/cleanup | Passed inside its private network namespace |
| Real QCOW2 checkpoint, source mutation and independent restore | Passed; guest-visible content and permissions checked |
| PHP isolated handler suite | **142 tests, 540 assertions; no warnings, deprecations or notices** |
| PHP strict mode | Passed with `--fail-on-warning --fail-on-deprecation` |
| Actual QEMU process/offline proof | Passed on the running cold-import appliance |
| Challenge source suite after directory moves | **55 passed**, eight sheets/walkthroughs checked |

The first PHP run exposed stale OS-upload fixtures, obsolete synchronous VPN
signup tests and a signup commit failure path. The final suite uses current
contracts and verifies rollback before authentication. It also tests the review
checkout even when Composer dependencies are reused through a vendor symlink.
Fixture-only collaborators use stubs; expectation-bearing mocks remain mocks.

## Storage contention finding

During a concurrent bulk migration to `/mnt/data`, the outer SATA controller
reported FLUSH CACHE timeouts and the nested web VM reported NCQ read/write
timeouts. PHPUnit initially failed to read a vendor file with `EIO`. Pausing
bulk I/O cleared the read failure; the complete PHP suite then ran in under one
second. The host kernel showed no physical `/dev/sda` or NVMe I/O errors in the
inspected log. This is not a physical disk health certification.

Do not run large artifact transfers while collecting nested runtime acceptance.
The appliance was gracefully stopped before the migration resumed. Keep this
failure as a release reliability finding: capacity/storage load testing and
crash/recovery rehearsal are still required. The successful idle cold-import
acceptance of the previously sealed OVA does not establish load reliability.

## Not claimed

Container-backed PHP database tests and the full Playwright suite were not run
for this branch. CI is configured but was not executed remotely. The backend
update transaction's failures are covered with injected service boundaries;
real service interruption, power-loss and production main-to-release migration
still require staging rehearsal. The existing challenge-specific cold cycle
belongs to the earlier sealed deployment-fix baseline, not these new API/web
changes. No production host was changed and no production acceptance is granted.
