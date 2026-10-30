# Rollout validation — 2026-10-30

This is an implementation validation record, not production acceptance. Production
has not been contacted or changed. The rehearsal uses a disposable overlay of the
existing local appliance with its three infrastructure VMs and synthetic accounts.
Its backend source baseline was associated with the verified upstream main commit;
its already-provisioned database/platform state is from the earlier pilot. It is
not a restored copy of the current production database or host configuration.

## Recorded checks

- Portable Python suite: 131 tests, eleven environment-dependent skips. This includes
  durable recovery/write-boundary behavior, migration/plan validation, database
  backup failure handling, CLI imports, service guards and TLS pin/auth ordering.
- Original fixture backup interruption: maintenance remained closed; an uncertain
  submission was recorded instead of automatically resubmitted. The exact matching
  PVE task was identified from node history and adopted through the journal API.
- PVE CLI dispatch was replaced with pinned local HTTPS dispatch. Local root signs
  a short-lived ticket using the installed PVE signer; credentials stay in memory.
  A live authenticated node/VM query succeeded. The username quoting regression is
  covered by a test.
- Network verifier: actual outer QEMU `restrict=on` profile and sampled outbound
  TCP denials passed for the running fixture.

## Whole-VM failure recovery passed

The first full checkpoint verified all three compressed VMA archives. Deployment
then refused a web baseline mismatch; the restored comparison identified only
`composer.lock`, which the former installer changed through `composer update`.
The controller restored all three infrastructure VMs and original source, verified
old health and the protected account/grade hashes, and cleared maintenance. The
transaction reached `ROLLED_BACK` without committing the failed release. The adapter
now preserves/fingerprints the installed resolved lock and vendor metadata.

## Rehearsal in progress

A successful complete update, deliberate migration failure, postcommit resume
and deliberate rollback still require
completed evidence. Do not treat the preceding checks as those acceptance tests.
The fixture's state/journal and backup disk remain private under the local build
root; the sealed upload OVA and original appliance disk are unchanged.

## Required before production

Restore a real production backup into an isolated clone, verify its baseline, and
rehearse the exact pinned release and its complete recovery. Verify account/grade
preservation, login/launch/solve/teardown, monitoring, an independent boot, and
failure paths under realistic storage load. Confirm external console access and
host OS/network backup recovery separately. The earlier validation in
`LOCAL-VALIDATION.md` belongs to the parent branch and does not validate this rollout.
