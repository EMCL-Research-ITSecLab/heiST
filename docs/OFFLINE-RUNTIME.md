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

Release planning must compare bundle source bytes with the target's immutable
Git objects and requirements, then pin the full artifact hash. The installer
checks that pinned hash again, creates an immutable versioned venv, installs with
`--no-index --no-deps --require-hashes`, checks dependencies and imports the app.
It records the complete installed runtime inventory. Activation verifies this
inventory before atomically switching the `current` link. It does not mutate an
existing runtime or the Proxmox host's existing `.venv`.

The systemd template references the active source through `PYTHONPATH`. Private
configuration belongs in `/etc/heist/web.env`; writable data belongs in
`/var/lib/heist-web`. Neither is part of the runtime artifact. The candidate
installer deliberately does not provision accounts, secrets, Apache, migrations,
media or services by itself. Their checked deployment and rollback integration
must complete before this is a production release procedure.
