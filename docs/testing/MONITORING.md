# Monitoring acceptance

Run fault injection only on the disposable appliance. Production inspection is
read-only unless a specific maintenance change is approved. Retain the exact
commit, artifacts, infrastructure versions, UTC timestamps and sanitized results.
Do not save real terminal commands, credentials or packet contents in test reports.

## Automated contracts

`tests/test_monitoring_health.py` covers stopped/missing services, mixed-success
systemctl output, idle oneshot jobs, AF_PACKET and NFQUEUE statistics, capture
configuration drift, dummy interface flags, Wazuh containers, empty Grafana
inventory, missing/malformed/oversized/stale/future receipts, bounded remote
collection, private atomic publication and output field filtering.

`tests/test_web_administration.py` checks authentication and role revocation at
the operations endpoint. `frontend/tests/monitoring.test.ts` checks ordering,
unknown states and stale evidence. `tests/browser/ui_smoke.py` renders a failed,
stale monitoring receipt without issuing a mutation. The responsive layout suite
also visits the operations page. These tests use synthetic data and do not
establish real event delivery.

`tests/test_suricata_fanout.py` is an opt-in privileged kernel regression. It
creates two dummy capture interfaces in a fresh network namespace and verifies
that shared group99 is rejected across interfaces while separate group100 works.
It captures no frames and changes no host interfaces. This reproduces the kernel
constraint behind the deployed configuration drift; it does not reconstruct the
historical startup log or replace a live sensor/flow rehearsal.

## Appliance acceptance matrix

Test the real nonroot observer unit separately, after staging the matching runtime
with `rehearse_monitoring.py`:

```sh
sudo python3 tools/local/rehearse_watchdog.py --work /private/pilot \
  --artifact /private/watchdog.pyz --commit FULL_COMMIT \
  --output /private/pilot/evidence/observer-run
```

The observer runs on the monitoring VM as a surrogate off-host collector. It uses
the actual service template with fixture account/paths, real systemd credentials,
an in-VM generated key restricted to reading one synthetic source receipt, and a
pinned source SSH host key. Healthy, failed, stale and incorrect-host-pin cases
must alternate with successful recovery, unique job invocations and nonroot
journal entries. The temporary service and observer private key are removed, and
only its restricted source authorization is removed. This verifies real transport
and deployment permissions; its **synthetic service inventory** cannot certify
application/guest health or replace a production-clone upgrade rehearsal.

For a verified offline pilot, run the real component rehearsal from an exact
source-bound runtime:

```sh
sudo python3 tools/local/rehearse_monitoring.py --work /private/pilot \
  --runtime-bundle /private/runtime.tar.gz --commit FULL_COMMIT \
  --output /private/pilot/evidence/monitoring-run --faults --canary
```

It stages code separately under `/opt/heist-monitoring-rehearsal/`, without
upgrading the installed application. It stops/restores the monitoring VM's node
exporter and verifies Prometheus detects the outage and recovery. A temporary DMZ
sensor uses distinct fanout and a unique test rule, injects four documentation-net
UDP frames through a temporary veth ingress mirror into the IFB/dummy device,
then checks a matching EVE alert and an
authenticated certificate-pinned ClickHouse aggregate. The original sensor config
is never edited; the prior service-active state is restored in `finally`.

The packet injection validates **one temporary veth tc mirror**; guest NIC/bridge mirror coverage,
command logging, PCAP archival and full application upgrade/rollback are not
certified by this component test. A legacy OVA without Git metadata cannot be
silently relabelled as a supported upgrade baseline. Use a reconstructed supported
production clone for that separate acceptance. Evidence and diagnostic failures
stay in a new private directory; credentials and packet bodies are not exported.

### Native component results, 2026-11-10

The retained pilot OVA was cold-imported onto a separate disk. Its missing SSH
access was recovered through its console with a new disposable key; the sealed
OVA and original pinned host key were preserved. QEMU isolation and sampled
external connection denials were verified against the current guest boot.

Actual monitoring tests observed the node-exporter outage in both systemd and
Prometheus, followed by recovery. The nonroot observer passed seven real systemd
runs: healthy, failed service, recovery, stale receipt, recovery, wrong SSH host
pin, recovery. Each run had a distinct journal invocation. The observer's source
inventory was synthetic; these results verify its transport and permissions.

The packet rehearsal initially exposed a real failure: Vector was running but
trusted a different self-signed certificate from the one ClickHouse served. On
the disposable copy only, the public server certificate was fetched through
pinned SSH, verified with chain and IP-name checking, and installed as the fixture
trust file after saving its original. Certificate verification remained enabled.
After that fixture repair, all four synthetic frames were observed in EVE and
ClickHouse. The host collector now checks the configured TLS connections of all
four Vector sinks without sending credentials or events, and the off-host
watchdog requires that evidence. TLS success still does not prove ingestion.

These component results do **not** certify the complete platform upgrade,
rollback, real guest-network coverage, terminal auditing or PCAP archival. The
legacy appliance lacks the Git metadata required for a supported upgrade baseline.
Production was unchanged during these rehearsals.

| Path | Required positive evidence | Failure and recovery cases |
|---|---|---|
| Collector and browser | Every configured role appears; collection and rendered states agree; no secrets or student events in response/export | Kill collector, malformed receipt, future clock, timeout, unknown SSH key, missing role; stale banner appears; recovery requires a new valid receipt |
| Core host and infrastructure | Correct units, actual HTTPS health with trusted certificate, authenticated application query, VPN client handshake, DNS lookup and Proxmox API | Stop each component separately; port open but wrong protocol; failed certificate; role unavailable; restore and verify dependent paths |
| Timers and backups | Completed job plus recent verified source generation and independently restored database | Timer active but job failed; successful empty run with old source backup; archive full/lost mount; recover without deleting unverified source |
| Guest command audit | Unique harmless canary in each supported Linux shell/noninteractive mode and Windows process/PowerShell event class, with exact guest and instance attribution | Agent stopped, audit disabled, root tampering, event queue full, shell builtins/history disabled; unsupported classes remain explicitly unverified |
| VPN capture | Known IPv4/IPv6 TCP/UDP/ICMP exchange between student and intended VM reaches sensor and downstream storage | Sensor down, wrong interface, shared fanout, missing mirror, wrong protocol selector; verify rule restoration and no cross-student capture |
| Internal and DMZ capture | Known guest↔guest traffic on the same bridge, separate networks and multihomed guest; NAT and reverse direction; ARP/L2 as specified | Missing switched traffic, asymmetric capture, NAT misattribution, duplicate ingress/egress observations; management traffic remains excluded |
| Suricata and Zeek | Unique flow/alert appears at expected sensor, event timestamps align and counters move | Healthy daemon with wrong rules/interface; missing stats; capture/queue drops; rotate during traffic and restart without unexplained gaps |
| Vector → ClickHouse | Correlated canary stored once/as documented; source event count, sink count and bounded delivery latency recorded | Wrong credentials, broken CA, sink outage, rejected VRL, buffering exhaustion, inode-changing rotation; recovery proves replay/deduplication behavior |
| Wazuh → indexer | Agent connected and canary searchable with correct host/session identity | Manager up but indexer unavailable, enrollment mismatch, duplicate Agent ID, stale agent; reconcile without deleting another VM's registration |
| Grafana | All six expected dashboards exist, authenticate and return expected canary data with correct time/filter scope | Missing dashboard/plugin/data source, query error, stale series, anonymous access attempt; admin credentials never sent to browser |
| Closed files → archive | SHA256 and size match, gzip/PCAP parse independently, manifest complete and time interval/capture point known | Open/changing source, interrupted copy, full filesystem, missing mount, invalid checksum; retry never publishes an unverified dataset |
| Resource and time health | CPU/RAM/load, source and capture filesystems, inodes, buffer capacity, clock offset and storage throughput measured at lecture concurrency | Threshold crossing, disk/inode exhaustion, clock skew and restart; verify alert delivery and recovery hysteresis |
| Attribution and permissions | Two simultaneous students and a VM/IP reuse cycle remain correctly scoped by immutable IDs and time intervals | Student/nonadmin, revoked admin, guessed instance/VM IDs, unsafe Grafana variables, forged query; no cross-instance command/packet access |
| Independent alerts | An off-host observer detects missing platform heartbeat and a known failed check within the agreed deadline | Backend/UI/Proxmox unavailable; notification still arrives without relying on the failed host; deduplicate and resolve after verified recovery |
| Upgrade/reboot | Collector trust/config/receipts and enablement survive reviewed upgrade and host/VM reboot | Interrupted install, rollback and old/new schema mismatch; recovery preserves existing archive data and marks stale evidence explicitly |

Initial acceptance targets: collector interval one minute after completion,
snapshot staleness 180 seconds, UI refresh 30 seconds. Measure real collection
duration under load; set event delivery latency, packet-loss budget, archive RPO,
retention and alert deadlines before production activation. A surviving timer or
an HTTP200 response is insufficient evidence.

The collector implements service inventory, root storage/inodes, available memory,
CPU-normalized load, clock synchronization, sensor heartbeat/configuration,
Proxmox-reported storage, source-backup freshness and receipt contracts. The seven
expected Prometheus jobs must report fresh successful scrapes. Authenticated
probes check Wazuh agent metadata, Grafana health
and expected dashboards, and fresh ClickHouse sensor statistics. Administrator
instance inspection projects only its current VM IDs. Rollout stages/checkpoints
collector configuration and units. The independent observer reports to the systemd
journal and its standalone artifact is tested through healthy/failure/recovery.

`tests/test_monitoring_pipeline.py`, `tests/test_monitoring_deployment.py` and
`tests/test_monitoring_watchdog.py` cover these additional paths, including invalid
TLS/credentials, missing/partial inventory, cross-instance filtering, critical
service evidence and the packaged observer's real exit code without site-packages.

Remaining native acceptance includes deploying these components to the isolated
appliance, full upgrade/failure/rollback, actual off-host outages and recovery,
correlated command/flow canaries, all capture points and full-PCAP archival.
Application/TLS probes for the web/database roles, panel query correctness and
complete command/packet coverage remain separate requirements. CPU load is not a
utilization measurement. Keep these limitations visible; portable tests do not
prove the complete platform paths.

## Dataset acceptance for later ML use

Create an isolated fixture with known packet/command counts and scenario labels.
Capture on every declared point at idle, nominal load and peak lecture load.
Compare independently generated ground truth with sensor counters, EVE/Zeek rows
and parsed PCAP records. Explain every missing or duplicate observation. Validate
full packet length, IPv4/IPv6/L2 scope, UTC alignment and encrypted payload limits.

Interrupt storage and shippers, rotate and reboot, then verify every closed file's
manifest, checksum, interval and provenance. An unexplained gap labels the dataset
incomplete; never silently train on a supposedly complete recording. Test retention
and deletion of the separate student-identity mapping as well as the capture files.
Record privileged guest tampering as a limitation of command ground truth.

See [the operator monitoring guide](../administration/MONITORING.md) for deployment
templates, the production inspection and the proposed frontend/data architecture.
