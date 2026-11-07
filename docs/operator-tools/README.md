# Operator tools

Run these commands from the repository root. They are explicit workstation tools;
importing an application package never starts them.

| Task | Command |
|---|---|
| Import a challenge YAML and its images | `python3 -m tools.challenges --help` |
| Configure/build a VM image | `python3 -m tools.images --help` |
| Convert an existing VM to OVA | [Conversion guide](ova-conversion.md) |
| Copy closed log archives | `python3 -m tools.maintenance.archive_logs --help` |
| Build a frontend release artifact | `python3 -m tools.frontend --help` |
| Run an isolated heiST appliance | [Local appliance guide](../LOCAL-APPLIANCE.md) |

Challenge imports use the public HTTPS web origin, trusted CA verification and a
normal administrator session. Supply `--url`, `--username`, and `--ca-file` when
using the lab CA; enter the password at the prompt. Images and challenge creation
use that same origin. There is no default administrator password. The helpers now use Flask `/api/`
endpoints and rotate their CSRF header after login. Uploads stream raw server-sized
chunks, seal the transfer, then wait for a confirmed `READY` artifact before
creating an exercise. A pending or uncertain result retains the receipt and is
not retried as a second upload. Declare `guest_os: windows` in a YAML machine entry
for Windows artifacts; Linux is the default. Redirects and unverified TLS are
refused.

Image building requires the explicit `--execute` option. Keep output under
`HEIST_BUILD_ROOT`, normally `/mnt/data/heist-builds`, rather than the source tree.
The log archiver checks SSH host keys and downloaded checksums. Copying is the
default; `--remove-remote` explicitly removes a verified, unchanged remote archive.
