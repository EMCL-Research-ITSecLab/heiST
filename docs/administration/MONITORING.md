# Platform and challenge monitoring

Use **Platform status → Platform monitoring** for the administrator health
inventory. The existing database, archive and release diagnostics remain separate.
The collector is read-only: it never starts services, changes capture rules,
records new student activity or repairs infrastructure. No new dependency is needed.
This is the initial health inventory, not certification of complete telemetry.

## Health checks

| Role | Checks implemented |
|---|---|
| Proxmox host | Backend, pool manager, startup cleanup, PVE daemons, backend DNS, OpenVPN, all three Suricata sensors, four Vector shippers, Zeek, expiry and log-preparation timers and last job results |
| Host capture | Recent EVE statistics, AF_PACKET packet/drop counters, NFQUEUE heartbeat, distinct VPN/DMZ fanout groups, configured capture interfaces present and administratively up |
| Monitoring VM | Grafana, ClickHouse, Docker, the three Wazuh Compose containers, nonempty Grafana dashboard inventory |
| Web VM | Flask/Gunicorn unit and Apache |
| Database VM | PostgreSQL unit and local connection readiness; the operations API separately executes an application database query |
| Archive VM | Database and log collection timers and their last job results; verified-file delivery is reported by the existing archive receipt |
| All roles | Root filesystem capacity and clock synchronization |

The fixed service inventory follows the current deployment layout. Review unit
names, Wazuh Compose names and paths when changing provisioning. An unknown or
missing component must remain visible; do not remove a failing check to turn the
page green. Capture mounts other than `/` require their own capacity monitoring.

`ok` means only the check's stated evidence succeeded. Recent Suricata statistics
are a sensor heartbeat even without traffic. Cumulative kernel drops produce a
warning; they are not a measured drop rate. NFQUEUE uses different counters from
AF_PACKET. Dummy interfaces may correctly report an `UNKNOWN` operational state:
the collector checks their administrative `UP` flag instead.

Inactive successful oneshot jobs are normal between timer runs. Never-run jobs
remain unknown. Wazuh runs in containers, so an absent host `wazuh-manager.service`
is not an outage. A stopped/missing required daemon or timer is a failure.

Each role deliberately includes an **unverified end-to-end check**. The initial
collector does not authenticate Grafana data-source queries, query ClickHouse
row freshness, inspect Wazuh agent coverage, validate tc/iptables attachment,
or certify packet completeness. Therefore an otherwise successful inventory
still reports `unknown`. Idle traffic, an empty archive batch and a missing
canary cannot prove delivery. These distinctions prevent false green status.

## Configure the collector for a reviewed release

The files are staged for deployment; existing installations are not modified
automatically. The current release controller does not yet install or checkpoint
these new units. Include their configuration, trust files and enablement state in
the next reviewed deployment/recovery plan before enabling collection.

1. Review `deploy/monitoring/config/monitoring.example.json`. Replace every
   placeholder with the existing infrastructure host and SSH account for that
   role. Save as `/etc/heist/monitoring.json`, root-owned, mode0600. Do not use
   a student's exercise VM as an infrastructure role.
2. Verify and pin each infrastructure SSH host key through a trusted channel.
   Keep the existing private key on the host; never forward its agent or copy it
   to a VM. Collection uses pinned SSH and noninteractive `sudo python3` to run
   this fixed standard-library probe over stdin. It needs the operator's already
   authorized infrastructure access; do not grant students this sudo access.
3. Review the two units under `deploy/monitoring/systemd/`. Adapt the installation
   and virtualenv paths if they differ from `/root/heiST`. Install under
   `/etc/systemd/system/`, reload systemd, then start the service manually before
   enabling the timer. Systemd creates private `/var/lib/heist/monitoring` state.
4. Inspect `systemctl status heist-monitoring.service` and the status receipt.
   Correct configuration failures; service execution success does **not** mean
   health checks passed. Only then enable `heist-monitoring.timer`.
5. Set `HEIST_MONITORING_STATUS_FILE=/var/lib/heist/monitoring/status.json` in the
   privileged backend environment and apply it through the normal guarded
   backend restart/release process. The unprivileged web VM receives only the
   sanitized administrator API response, not filesystem or SSH access.

One-off inspection, without installing units or writing a receipt:

```sh
bin/heist monitor --role host
bin/heist monitor --role host --config /etc/heist/monitoring.json
```

The timer refreshes one minute after each completed collection, avoiding overlapping
jobs. Remote checks have a 15-second timeout per role; the service has a 90-second
deadline. Receipts are atomically replaced, mode0600, bounded to 64 KiB and considered
stale after 180 seconds. Future timestamps over 30 seconds are rejected. A failed
collector leaves its previous receipt to become stale; a missing configured file
is unavailable. HTTP requests read the snapshot and never initiate remote probes.
The UI refreshes every 30 seconds, orders failures first and labels stale evidence
as historical. Student accounts cannot read the administrator operations route.

The current unit uses root because existing platform units, sensor statistics
and monitoring containers require privileged reads. A dedicated reduced-privilege
probe endpoint is a later hardening step. The shipped collector adds no listener.

## Challenge visibility in the frontend

Use the native React interface for summaries and keep Grafana for detailed
instructor investigation. Do not expose Grafana administrator credentials in the
browser or enable anonymous access to bypass an iframe login. Grafana's embedding
and authenticated embedding options are documented in its
[configuration reference](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/)
and [JWT authentication guide](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/jwt/).

The next instance-level API should resolve instance → VM IDs → `Agent_<vmid>`
and network IDs on the server, then return agent last-seen, sensor state and
delivery timestamps. Scope queries using immutable instance and assignment IDs
and their start/end times; IP addresses are reused. Recheck the administrator role
and instance identity on every request. Grafana variables are filters, not access
control. Student views would need separate ownership enforcement and must never
query unrestricted terminal logs or another student's traffic. This instance-level
telemetry view is not implemented by the initial platform panel.

## Command telemetry

The existing Linux `PROMPT_COMMAND`/shell-history logger is incomplete and can be
disabled by a privileged guest user. It misses other shells and noninteractive
execution. Windows process creation auditing also does not imply complete
PowerShell scripts, keystrokes, terminal output or shell builtins are recorded.

For the next exercise image revision, test Linux execution auditing through the
existing Wazuh pipeline; see the official
[command auditing example](https://documentation.wazuh.com/current/proof-of-concept-guide/audit-commands-run-by-user.html).
Validate Windows 4688 command lines and PowerShell 4104 separately. Record which
event classes and guest OS versions are actually covered. Auditd or session
recording additions need a separately reviewed image/dependency change. Process
execution, interactive session recording and screen recording are different
requirements; do not label one as complete terminal monitoring. Guest-root
tampering remains a limitation even with a healthy agent.

## Full packet capture and ML datasets

Suricata EVE and Zeek events are structured metadata; they do not replace PCAP.
Existing configuration enables some PCAP output, but its completeness, retention,
capture points and successful archival have not been accepted. Suricata's
[packet logging reference](https://docs.suricata.io/en/suricata-8.0.0/configuration/suricata-yaml.html)
describes rotation and per-thread limits. Rotation alone does not guarantee delivery.

Before expanding capture:

- Define every intended capture point: student↔VM, VM↔VM within a bridge,
  multiple internal networks, DMZ/NAT and both directions. Existing mirror rules
  use IPv4 protocol selectors; verify IPv6 and ARP/L2 separately. Bridge-level
  filters do not establish coverage of all switched guest traffic. Keep platform
  management and unrelated production networks outside challenge capture.
- Use full packet lengths and bounded rotating files. Measure sensor, mirror,
  queue, NIC and storage drops; identify duplicate observation points. Encrypted
  payloads remain encrypted. Never describe an unmeasured capture as lossless.
- Transfer only closed captures with checksum manifests and verified storage
  receipts, extending the existing archiver deliberately: it currently handles
  gzip rotations and database backups, not a complete PCAP lifecycle.
- Store UTC intervals, clock offsets, exercise/image revision, instance/VM/network
  IDs, capture point, filter, packet/byte/drop counts, checksum and scenario labels
  in each dataset manifest. Keep student identities in a separate restricted
  mapping. Split training/test sets by session or scenario to avoid leakage.
- Agree the collection notice, access controls, retention, deletion and dataset
  distribution process before collecting a broader dataset. Commands and packets
  can contain credentials; do not publish raw recordings in Git or UI exports.

Capacity must be measured before activation: continuous 100 Mbit/s is approximately
1.08 TB/day, and 1 Gbit/s is 10.8 TB/day before overhead. The current 1.5 TiB archive VM
cannot retain sustained full-rate traffic for long. Keep the existing 100 GiB reserve
and define backpressure/retention behavior before enabling a capture spool.

## Production inspection, 2026-11-10

Read-only inspection of the host and monitoring VM found:

- `suricata-dmz.service` failed, DMZ EVE empty; VPN and backend sensors running.
- Deployed VPN and DMZ AF_PACKET configuration both use fanout group 99; the
  corrected source generator uses 99 and 100. Treat this as verified configuration
  drift. The retained logs do not prove the original startup failure cause.
- Grafana running with anonymous access disabled and three configured data sources,
  but zero stored dashboards. Wazuh's three containers and ClickHouse were running.
- The initial localhost Grafana TLS probe did not validate its certificate; this
  is an unverified HTTPS check, not proof that Grafana itself is down.

No services, capture settings or dashboard configuration were changed during this
inspection. Repair the DMZ generated configuration and validate it in isolation
before a guarded restart. Provision the expected six source dashboards through a
certificate-verified client and test their data queries. The legacy Grafana updater
globally disables requests certificate verification on import; the health collector
does not import it. Replace that behavior before reusing the updater in a service.

See the [monitoring acceptance matrix](../testing/MONITORING.md) for the required
rehearsals. Neither these observations nor portable tests certify complete capture
or authorize a production monitoring rollout.
