# Disposable local heiST appliance

The standard-library tools in `tools/local/` run a full Proxmox/heiST OVA on
an x86-64 Linux workstation with KVM and nested virtualization. They do not
change workstation bridges or routes. Install QEMU, qemu-utils, OpenSSH and
xorriso using the workstation's normal package manager.

Keep all disks, credentials and logs outside the checkout. A private appliance
contains its installed administrator credentials and challenge solutions.
The repository contains source, not an appliance download or shared password.

## Import and run an existing appliance

The current importer accepts the single-disk BIOS/SATA, E1000 profile produced
by this exporter, including large disks split into OVF chunks. It validates
archive paths, member types, manifest coverage, capacities and resource counts.
It does not import arbitrary multi-disk or UEFI OVAs.

```sh
python3 tools/local/pilot_appliance.py cold-import \
  --ova /absolute/path/heiST-nested-pilot.ova \
  --work /mnt/data/heist-builds/runs/my-cold-import \
  --access-source /absolute/private/original-pilot-access
sudo python3 tools/local/nested_pilot.py \
  --work /mnt/data/heist-builds/runs/my-cold-import start
sudo python3 tools/local/nested_pilot.py \
  --work /mnt/data/heist-builds/runs/my-cold-import status
sudo python3 tools/local/verify_pilot_offline.py \
  --work /mnt/data/heist-builds/runs/my-cold-import
```

`--access-source` supplies the matching SSH private key and known-hosts file
from the appliance owner; the OVA does not distribute that private key. A cold
import is an independent disk with no cloud-init seed. It never overwrites an
existing workspace. Reserve twice the virtual disk capacity plus 8 GiB for
reassembly/conversion. Memory and vCPU counts come from the descriptor; the
operator must check available host capacity before starting it.

Only loopback forwards are exposed: HTTPS `18443`, SSH `22220`, Proxmox `18006`
and OpenVPN UDP `11194`. Default QEMU `restrict=on` blocks guest-initiated
external traffic. The verifier checks the actual process/network arguments and
samples TCP denials tied to the guest boot ID. This is not an exhaustive audit
of DNS or all protocols. Do not treat a marker file alone as isolation proof.

The pilot SSH identity is `heist-pilot` and has `/root/pilot-cloud-init-ready`;
verification intentionally refuses unrelated machines. Browse
`https://127.0.0.1:18443` using the appliance's private administrator credentials.
Guest certificate trust must be configured for the test appliance.

## Build, checkpoint and installation rollback

`nested_pilot.py --work /absolute/new/work prepare --image BASE.qcow2 --sums
SHA512SUMS` validates a standalone Debian image against its supplied official
manifest. Use `start --online` only for initial OS/platform provisioning;
`provision-proxmox` installs Proxmox inside this disposable guest. Install heiST
normally inside it with `bin/install`. Before running an installer or release
migration, shut the outer guest down and clone the complete standalone disk
using `sudo python3 tools/local/nested_pilot.py --work OLD_WORK checkpoint
--output NEW_CHECKPOINT`. It clones the standalone disk, verifies guest-visible
content using `qemu-img compare`, and preserves configuration, matching SSH
access and seed inputs privately. A failed conversion/comparison leaves no valid
checkpoint receipt. Wait for the QEMU process to exit first. An online filesystem copy is not a valid rollback.

For rollback, stop the failed appliance and run the same checkpoint command
with `--work CHECKPOINT --output NEW_RESTORED_WORK` to create an independent
restore; retain the failed disk for diagnosis. This restores the host,
VMs, database, packages and configuration together. Start only one copy with the
fixed loopback ports. It is an isolated installation rollback, not a production
backup strategy. Production physical hosts require tested VM/database/host
configuration backups as described in [UPDATES.md](UPDATES.md).

`pilot_appliance.py export --work WORK --output NEW_RELEASE` requires a stopped,
standalone QCOW2 and a shutdown proof asserting stopped guests, portable
management networking and disabled cloud-init. The tool checks those assertions;
it does not itself reconfigure arbitrary hosts for export. Cold-import every
export and test its real UI, API, VPN, grading, isolation and cleanup before
calling that specific OVA accepted. The Senior Identity repository supplies
challenge-specific fixtures and solvers; the runner has no dependency on them.

Run runtime acceptance separately from bulk transfers or image exports. Concurrent
bulk I/O caused nested SATA timeouts during local validation; see
[LOCAL-VALIDATION.md](LOCAL-VALIDATION.md).

For the supplied Senior Identity pilot OVA, follow its appliance guide after a
new boot: the deliberately bounded pilot worker also needs the fresh offline
proof and an idle backend/pool restart. That pilot wrapper is separate from the
normal heiST worker configuration. Never restart a backend with live challenges
solely to satisfy a test harness. Workspace aliases are resolved before QEMU
starts, so `runs/current-appliance` and the direct workspace use the same proof.

## Rollout rehearsal backup volume

A disposable pilot may attach a separately created, private standalone
`backup.qcow2` by setting `attach_backup_disk: true` in its private `pilot.json`.
The device is identified as `HEIST-ROLLOUT-BACKUP`; identify it explicitly before
formatting/mounting it for administrator checkpoints. The launcher does not format
or mount disks. Single-disk checkpoint/export commands refuse this attachment
rather than silently omitting its data.

See [rollout validation](ROLLOUT-VALIDATION.md) for the explicit recovery and web
reboot rehearsals. Retain the verified update baseline and newer rollback safety
checkpoint. A test overlay also depends on its backing image; keep that image
until the overlay is removed or converted to a stopped standalone disk.
