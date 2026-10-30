# Separate archive VM

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
sudo install -m 0644 tools/maintenance/archive_logs.py /usr/local/lib/heist/archive_logs.py
sudo install -m 0644 deploy/archive/systemd/heist-log-archive@.{service,timer} /etc/systemd/system/
sudo install -d -m 0750 -o root -g heist-archive /etc/heist/archive
sudo install -d -m 0700 /etc/heist/archive/keys
sudo install -m 0640 -o root -g heist-archive deploy/archive/config/web.example.json /etc/heist/archive/web.json
```

Set the real source host, read-only source account and closed-log directory in
`web.json`. Never share a destination across sources. Default destinations are
under `/var/lib/heist-archive/SOURCE`. Mount the archive data volume at
`/var/lib/heist-archive`; ensure it is owned by the service account with mode
0700. Add `AssertPathIsMountPoint=/var/lib/heist-archive` in a service drop-in when
using that volume, so a missing mount cannot fill the archive VM's root disk.
Do not enable timers before that mount assertion has been rehearsed.

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
HEIST_ARCHIVE_STATUS_FILE=/var/lib/heist-archive/web/status.json
HEIST_ARCHIVE_MAX_AGE_SECONDS=1800
```

Configure the backend host's SSH alias with a dedicated identity and pinned host
key. On the archive VM restrict that key to the fixed command
`head -c 65537 -- /var/lib/heist-archive/web/status.json`, with forwarding/PTY
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
[test concept](TEST-CONCEPT.md) before deployment.
