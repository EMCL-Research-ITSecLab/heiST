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

## Appliance acceptance matrix

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
CPU-normalized load, clock synchronization, sensor heartbeat/configuration and
receipt contracts. Authenticated probes check Wazuh agent metadata, Grafana health
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
