# Separate archive VM

The collector now lives in `tools/maintenance/replicate.py`. One configuration
and systemd timer instance represents one source. `kind: "logs"` copies closed
gzip archives; `recursive: true` includes dated rotation directories and skips
symlinks. `kind: "database"` copies complete generations from
`/var/backups/heist/database`, including their `metadata.json` and custom-format
dump. It ignores `.pending-*` directories, verifies size and SHA256, and publishes
each generation atomically. Database replication never removes source copies.

Use `deploy/archive/config/proxmox-logs.example.json` and
`database.example.json` for these sources. Configure a free-space reserve;
it is checked before each new file or database generation as well as at startup.
Do not delete source logs until a copied-file restore and the failure cases below
have been verified. A missing timer or an empty archive is not a successful backup.

Install the existing Paramiko dependency for the dedicated service account. Pin
the source's SSH host key through a trusted channel. `LoadCredential` can read an
existing protected key on the collector host; a private key need not be copied
off its host. If `public_status` is configured, create its parent directory owned
by the collector with mode 0755. It publishes only the bounded receipt (source,
timestamps, status, counters and error type), with mode 0644; archive contents stay
private. Create `/var/lib/heist-archive/status` before starting the unit.

The destination must be an explicitly mounted storage path. On a dedicated
storage VM whose large data volume is also its root filesystem, a reviewed bind
mount can supply this mount guard; it does not create an independent disk. Reserve
root capacity explicitly. Never format an existing filesystem to set this up.

Run log archiving on the dedicated archive VM. The application/source machines
rotate and close logs; the archive VM pulls only closed `.gz` files over SSH.
Source removal is off by default. Each source has a separate service, timer,
SSH identity, destination, lock and private status receipt. No additional framework
is needed: the script uses the platform's existing Paramiko dependency.

## Install on the archive VM

These commands are an operator procedure, not actions performed on production by
this change. Install the distribution's `python3-paramiko`, a system account
`heist-archive`, and these reviewed source files:

```sh
sudo install -d -m 0755 /usr/local/lib/heist
sudo install -m 0644 tools/maintenance/replicate.py /usr/local/lib/heist/replicate.py
sudo install -m 0644 deploy/archive/systemd/heist-log-archive@.{service,timer} /etc/systemd/system/
sudo install -d -m 0750 -o root -g heist-archive /etc/heist/archive
sudo install -d -m 0700 /etc/heist/archive/keys
sudo install -m 0640 -o root -g heist-archive deploy/archive/config/web.example.json /etc/heist/archive/web.json
```

Set the real source host, read-only source account and closed-log directory in
`web.json`. Never share a destination across sources. Default destinations are
under `/var/lib/heist-archive/files/SOURCE`. Mount the archive data volume at
`/var/lib/heist-archive`; make its root owned by root with mode 0751, and keep each service
subdirectory private to its own account. The unit asserts that this is a mount
point, so a missing volume cannot silently fill the archive VM's root disk.
Rehearse that assertion before enabling timers.

Create a dedicated source-reader SSH key per source; install its private key as
`/etc/heist/archive/keys/web.key` with root-only permissions. Pin the independently
verified source host keys in `/etc/heist/archive/known_hosts`. The service uses
systemd `LoadCredential=` to provide these files privately to its unprivileged
process. The source account must read only the intended closed log directory and
run `sha256sum`; it must not have sudo, write access to active logs, forwarding or
access to other students' private application data. Use SSH key restrictions and
filesystem permissions. Do not copy an administrator's general-purpose SSH key.

```sh
sudo systemd-analyze verify /etc/systemd/system/heist-log-archive@.service /etc/systemd/system/heist-log-archive@.timer
sudo systemctl daemon-reload
sudo systemctl start heist-log-archive@web.service
sudo systemctl status heist-log-archive@web.service
sudo journalctl -u heist-log-archive@web.service
sudo systemctl enable --now heist-log-archive@web.timer
sudo systemctl list-timers 'heist-log-archive@*'
```

The timer runs every five minutes, with a short randomized delay and persistent
catch-up after downtime. systemd avoids starting a second instance of an already
active unit; the script's file lock also rejects concurrent direct runs. A run
has a 15-minute timeout. Adjust the schedule/timeout to measured file sizes and
network capacity; monitor repeated timeout failures. The official
[timer documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
and [execution/credential documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
describe those unit semantics.

## Status in the administrator console

Each source writes private `status.json` with start/completion timestamps, latest
success and verified/copied byte/file counts. Failures retain the previous success
timestamp and record an error class, not exception text or credentials. A killed
or disk-full process may leave a running/stale receipt: check the service result
and journal as well as the receipt. A successful empty run does not prove that
upstream log production is healthy.

The backend can read one source receipt over a dedicated read-only SSH connection:

```dotenv
HEIST_ARCHIVE_STATUS_HOST=heist-archive-status
HEIST_ARCHIVE_STATUS_USER=heist-archive
HEIST_ARCHIVE_STATUS_FILE=/var/lib/heist-archive/files/web/status.json
HEIST_ARCHIVE_MAX_AGE_SECONDS=1800
```

Configure the backend host's SSH alias with a dedicated identity and pinned host
key. On the archive VM restrict that key to the fixed command
`head -c 65537 -- /var/lib/heist-archive/files/web/status.json`, with forwarding/PTY
prohibited. This connection cannot start a service, change logs or read arbitrary
files. Allow the account a shell only for this forced command and keep password
login disabled. The backend bounds the read and timeout and exposes only
sanitized fields. Missing configuration, unavailable SSH and stale receipts are
shown explicitly; no archive success is inferred from the application being up.

## Retention and recovery

Leave `remove_remote=false` until the full failure and restore rehearsal passes.
If remote removal is required, grant removal only for that closed-log directory
and record the retention decision. The script verifies the download, flushes its
file/directory, checks source identity/size/mtime and checks the remote digest
again before deletion. Producers must publish immutable closed files: no generic
SFTP client can atomically verify and remove a file that another actor is still
rewriting. Active logs are deliberately excluded.

There is no automatic deletion of archived data. Set source rotation, destination
capacity, retention, off-VM backup and restore requirements explicitly. Verify
sample restoration and digest comparison on independent storage. Run
`ARCHIVE-TIMER`, `ARCHIVE-FAILURES` and `ARCHIVE-RESTORE` from the
[test concept](../testing/TEST-CONCEPT.md) before deployment.


## Native systemd journal collection

For service/system journals use the distribution's `systemd-journal-upload` on
sources and `systemd-journal-remote` on the archive VM. The closed-file timer above
covers file/packet-capture archives that journal transport does not contain.
Keep both pipelines in the source inventory and test their failure/restore paths.

Reviewed templates are under `deploy/archive/journal/`. Install the matching
systemd journal packages on supported sources/collector. The collector needs
systemd 253 or newer for the configured storage limits; sources need version 249
or newer for `NetworkTimeoutSec=`. Check `systemd --version` before installing
these snippets. Older collectors need a separately tested retention procedure;
silently ignored options do not enforce a storage limit. These minimums follow
the [collector 255 manual](https://www.freedesktop.org/software/systemd/man/255/journal-remote.conf.html)
and [upload 255 manual](https://www.freedesktop.org/software/systemd/man/255/journal-upload.conf.html).
Use a private journal CA,
one source certificate/key per machine, and a collector certificate matching
`ARCHIVE_HOST`. Keep CA signing keys offline and private keys outside Git; grant
read access only to the corresponding daemon account. Configure firewall access
to TCP19532 only from the intended source network. Do not enable plaintext HTTP
or set certificate verification to `all`/disabled.

Install source snippets as:

- `source/60-heist-persistent.conf` → `/etc/systemd/journald.conf.d/60-heist.conf`
- `source/60-heist-upload.conf` → `/etc/systemd/journal-upload.conf.d/60-heist.conf`
- `source/60-heist-restart.conf` → `/etc/systemd/system/systemd-journal-upload.service.d/60-heist.conf`

Replace the host placeholder and certificate paths, verify permissions, then
restart journald and enable the upload service. The package's upload unit must
retain its `--save-state` argument so it can resume from its saved cursor. Inspect
`systemctl cat systemd-journal-upload.service` on the target distribution.

Install collector snippets as:

- `collector/60-heist-remote.conf` → `/etc/systemd/journal-remote.conf.d/60-heist.conf`
- `collector/60-heist-storage.conf` → `/etc/systemd/system/systemd-journal-remote.service.d/60-heist.conf`

Create `/var/lib/heist-archive/journal` owned by the package's journal-remote
account with mode0700. Enable the vendor `systemd-journal-remote.socket`; the
service consumes its HTTPS socket descriptor. Confirm the vendor binary path,
service user and socket configuration with `systemctl cat` before activation.
Do not run the collector as root or change the file-archive directory ownership
recursively: journal collection and closed-file collection use separate accounts.

Set storage/retention limits from measured lecture volume; the shipped values are
starting limits, not a guarantee that a full semester fits. Source buffer limits
can cause loss during an extended collector outage. Verify delivery with a unique
`logger -t heist-acceptance TEST_ID` event from each source, inspect it using
`journalctl --directory=/var/lib/heist-archive/journal`, interrupt/restart transport,
and prove recovery without unexplained gaps/duplicates. Reject a source with an
unknown certificate and a collector with the wrong certificate. Check source
machine-ID uniqueness after cloning. TLS authenticates transport; it does not
prove a compromised lab machine's event contents are truthful.

The console's current file-archive receipt reports closed-file runs. Native
journal delivery must be monitored independently per source; a recent file receipt
is not proof of journal completeness. Consult the official
[journal upload configuration](https://www.freedesktop.org/software/systemd/man/latest/journal-upload.conf.html),
[collector configuration](https://www.freedesktop.org/software/systemd/man/latest/journal-remote.conf.html)
and [collector service](https://www.freedesktop.org/software/systemd/man/latest/systemd-journal-remote.service.html)
when validating the target OS package configuration.
