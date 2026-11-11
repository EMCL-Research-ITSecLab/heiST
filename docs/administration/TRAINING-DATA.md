# Network traffic for training

The operator-selected user policy is **eligible by default, with an opt-out**.
Signup has no training preference control. Existing accounts receive the same
default when migration0012 runs. Users can uncheck **Allow my challenge traffic
in training datasets** under **Profile → Training data** without
losing access to exercises. The setting applies to training use, not the existing
operational security monitoring.

This preference is not evidence of consent. In particular, default-on processing
must not be presented as opt-in consent. Establish and document the collection's
lawful basis and update the operator's notice with its actual purpose, access,
retention, rights and contact details before activation. See the EDPB's
[consent guidance](https://www.edpb.europa.eu/system/files/2026-04/edpb-summary-consent_en.pdf).

## Implemented controls

Migration0012 adds private current preferences and a history of changes.
Restricted web roles can access only the stored functions; the HTTP API derives
identity from the authenticated session, ignores supplied user IDs and requires
CSRF protection for changes. Repeating the same choice is idempotent. A changed
choice increments a revision, including when a user later rejoins training use.
Preferences and their history are deleted with the account.

`heist.monitoring.training.eligibility` rejects any capture with an opted-out,
unknown or deleted participant, changed preference revision, incomplete scope,
invalid time interval, open file or missing checksum metadata. Every participant
must be known and eligible, including traffic peers. A shared VPN/DMZ/platform
PCAP is inadmissible; do not attempt to identify opted-out users afterward using
only IP addresses behind NAT. Use isolated instance capture points and a trusted
participant/assignment-generation manifest. Changing a preference cannot make an
old revision eligible again. Data predating the recorded policy state is blocked.

The command performs a fresh read-only database check and copies no data:

```sh
python -m heist.monitoring.training --environment /private/backend.env \
  --manifest /private/closed-capture.json
```

It returns a nonzero status for blocked or unavailable policy. Current training
capture is **disabled**: `HEIST_TRAINING_CAPTURE_ENABLED` is absent by default.
The default-on account preference does not turn on a capture service. Even after
acceptance, eligibility must be rechecked immediately before dataset export and
before training use; its result is not a reusable authorization token.

## Required before capture activation

This change does not install a training capture/export worker. The existing
shared security PCAP output and log archiver must not become a training source
merely by enabling the configuration flag. The gate validates trusted manifest
metadata; it cannot prove a collector's participant attribution is correct or
verify the source file's declared checksum by itself.

The dedicated worker still needs to:

- Bind capture points to a particular instance generation and complete participant
  set; reject unclassified/mixed traffic and verify IPv4, IPv6 and L2 coverage.
- Apply exclusions before writing training-purpose packets. Stop and acknowledge
  a changed preference, discard any chunk spanning an exclusion, and handle stale
  or unavailable policy by stopping capture. A periodic export check alone does
  not satisfy this capture requirement.
- Check file closure, checksum, packet/drop counters and storage reserve, then
  revalidate preferences when committing a dataset. Do not publish an allow
  receipt and leave a race between that receipt and copying data.
- Keep a private participant-to-chunk/dataset lineage ledger. On exclusion,
  quarantine pending chunks and find existing datasets and copies for removal.
  The current gate makes old revisions ineligible but does not physically delete
  copies already exported or undo models already trained.
- Define retention, deletion and access controls, keep identities separate from
  dataset labels, and test isolation, revocation, policy failure, archive failure,
  restart and recovery on a disposable challenge.

Keep training disabled on rollback until preference revisions and exclusion
history have been reconciled. Restoring an older database must never silently
re-enable a user's excluded traffic.

Use the new `releases/0.4.0-rc.4.json` manifest for this schema change. Previously
published release manifests were preserved. Full production-clone upgrade and
rollback acceptance remain separate prerequisites for rollout.
