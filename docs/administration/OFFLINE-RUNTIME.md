# Offline browser runtime

The candidate runtime builder packages trusted Git Python source and the pinned
Flask/Gunicorn dependencies for CPython 3.12 on Linux x86_64. It refuses dirty
source, missing/extra dependencies, duplicate wheel identities and unsupported
wheel targets. The installation host needs Python 3.12 with venv support, and
uses no package index during installation. A pinned copy of the existing pip
packaging tool bootstraps a stdlib venv without system ensurepip or an OS package
download. Use the web VM's system Python, not a private interpreter under `/root`.

Download only the existing approved pins on a workstation:

```sh
python -m pip download --only-binary=:all: --no-deps \
  --python-version 312 --implementation cp --abi cp312 \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 \
  -r deploy/web/requirements.txt -d /private/heist-runtime-wheels
python tools/build/runtime.py --wheelhouse /private/heist-runtime-wheels \
  --output /private/upload/heist-web-runtime.tar.gz
```

Use a wheelhouse containing only those wheels and a new output path. The builder
prints the source commit and artifact SHA256; retain both with the release.
Dependency pins and wheel hashes must be reviewed as release input. Bundle
checksums bind contents to the artifact, not to a publisher signature.

Schema-3 release planning compares every bundled Python source byte and the
requirements with the target's immutable Git objects, requires the matching
standalone UI bundle and pins both full artifact hashes. The CLI accepts
`--ui-bundle` and `--runtime-bundle` only when the release declares them. Schema-1
and schema-2 releases refuse an undeclared runtime. Planning tests reject altered
source even when an artifact's internal checksums have been recomputed.

The existing-installation Proxmox adapter supports schema-3 releases, including
versioned browser runtimes, database roles, templates and checkpointed recovery.
Published release manifests are under `releases/`. Applying a release normally
requires source-bound appliance acceptance; see [updates](UPDATES.md). A dated
operator waiver is an exception and never counts as a passing rehearsal.

The installer
checks that pinned hash again, creates an immutable versioned venv, installs with
`--no-index --no-deps --require-hashes`, checks dependencies and imports the app.
It records the complete installed runtime inventory. Activation verifies this
inventory before atomically switching the `current` link. It does not mutate an
existing runtime or the Proxmox host's existing `.venv`.

The systemd template references the active source through `PYTHONPATH`. Private
configuration belongs in `/etc/heist/web.env`; writable data belongs in
`/var/lib/heist-web`. Neither is part of the runtime artifact. The candidate
runtime installer deliberately does not provision accounts, secrets, Apache,
migrations, media or services by itself. The existing-installation rollout
coordinates those operations. Clean-host installation remains a separate,
unfinished acceptance path.


## Browser database and configuration boundary

The migration runner accepts a dedicated `heist_web_*` role and a generated
password only for the browser-runtime protocol. It creates the login, API schema
access and migration role binding in the same SQL transaction as the migrations.
A failing migration rolls back role creation as well as DDL and its ledger.
An existing role is refused for reconciliation. The role has no superuser,
creation, replication, bypass-RLS or inherited-role privileges, and a bounded
connection limit. PostgreSQL receives a salted SCRAM verifier, not a plaintext
password in SQL. Disposable PostgreSQL tests verify real login, wrong-password
denial, transaction rollback and the exact migration role binding.

`heist.rollout.browser_configuration` builds an explicit whitelist for the web
service: restricted database credentials, session secret, the internal operation
token and verified backend identity/CA. Proxmox tokens, root database passwords
and SSH settings are never copied. Native systemd testing verifies literal
EnvironmentFile handling; secrets travel through private files/service state,
never shell interpolation. These helpers still need the checked deployment
adapter to install the settings and activate the services.
