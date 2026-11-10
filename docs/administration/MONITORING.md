# Platform and challenge monitoring

Use **Platform status → Platform monitoring** for the administrator health
inventory. The existing database, archive and release diagnostics remain separate.
The collector is read-only: it never starts services, changes capture rules,
records new student activity or repairs infrastructure. No new dependency is needed.
This is the initial health inventory, not certification of complete telemetry.

## Health checks

| Role | Checks implemented |
|---|---|
| Proxmox host | Backend, pool manager, startup cleanup, PVE daemons, backend DNS, OpenVPN, all three Suricata sensors, four Vector shippers, Zeek, node/PVE exporters, Proxmox-reported storage capacity, source database-backup freshness, expiry/log-preparation timers and last job results |
| Host capture | Recent EVE statistics, AF_PACKET packet/drop counters, NFQUEUE heartbeat, distinct VPN/DMZ fanout groups, configured capture interfaces present and administratively up |
| Monitoring VM | Grafana, ClickHouse, Docker, Prometheus, node exporter, enrollment banner, three Wazuh containers, Grafana dashboard inventory and seven expected fresh Prometheus scrape jobs |
| Web VM | Flask/Gunicorn, artifact worker, Apache, node and Apache exporters |
| Database VM | PostgreSQL, node/PostgreSQL exporters and local connection readiness; the operations API separately executes an application database query |
| Archive VM | Database and log collection timers and their last job results; verified-file delivery is reported by the existing archive receipt |
| All roles | Root filesystem capacity/inodes, available memory, CPU-normalized system load and clock synchronization |

Prometheus is queried only on the monitoring VM's loopback port 9090, over the
existing pinned SSH transport. Redirects are rejected; target URLs and labels
are excluded from diagnostics. Every expected job must have fresh successful
scrapes. Proxmox capacity checks use its local read-only storage API through
`pvesh`; inactive enabled stores and data utilization at or above 95 percent fail.
Thin-pool metadata utilization still requires separate validation.

The source's published `latest.backup` must point to a complete PostgreSQL custom
archive with matching metadata size and an aware timestamp less than 30 minutes
old. This matches the current 15-minute backup schedule. An archive timer's recent
successful empty run cannot hide a stopped database-backup job. The freshness
probe does not replace the archiver's SHA256 verification or an independent restore.

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

Authenticated probes now check Wazuh managed-agent inventory, Grafana HTTPS/database
health and all six expected dashboards. ClickHouse read-only aggregate queries
check recent statistics in the VPN, DMZ and backend tables. Sensor statistics
provide a heartbeat even for a quiet exercise; no command or packet payload is
queried. These checks require explicitly configured credentials and TLS trust.

Each role still deliberately includes an **unverified end-to-end check**. Heartbeat
ingestion does not prove correct dashboard panels, command delivery, tc/iptables
attachment or packet completeness. An otherwise successful inventory therefore
remains `unknown`. Correlated canaries and fault/recovery rehearsals are required
before claiming full coverage.

## Configure the collector for a reviewed release

The protocol 3 full-platform rollout now stages the collector units and
`/etc/heist/monitoring.json` from the exact target commit. It derives infrastructure
hosts/accounts from the deployment description, adds the archive role when
`HEIST_ARCHIVE_STATUS_HOST` is configured, and sets `HEIST_MONITORING_STATUS_FILE`.
`HEIST_ARCHIVE_MONITORING_USER` defaults to `ubuntu`; the archive-receipt account
may lack sudo and is deliberately not reused for privileged health checks.

The configuration files and original service enablement/running states participate
in checkpoint/recovery. Previously absent units are disabled and removed on
rollback. A configured extra monitoring environment file is also checkpointed.
Portable recovery contracts pass; a full native upgrade/failure/rollback rehearsal
of this integration is still required. Production has not been changed. The
clean-host installer remains disabled.

For an independently reviewed manual installation, use the following procedure:

1. Review `deploy/monitoring/config/monitoring.example.json`. Replace every
   placeholder with the existing infrastructure host and SSH account for that
   role. Save as `/etc/heist/monitoring.json`, root-owned, mode0600. Do not use
   a student's exercise VM as an infrastructure role.
2. Verify and pin each infrastructure SSH host key through a trusted channel.
   Keep the existing private key on the host; never forward its agent or copy it
   to a VM. Collection uses pinned SSH and noninteractive `sudo python3` for
   non-root infrastructure accounts (direct Python for root) to run
   this fixed standard-library probe over stdin. It needs the operator's already
   authorized infrastructure access; do not grant students this sudo access.
3. Review `heist-monitoring.service` and `.timer` under `deploy/monitoring/systemd/`. Adapt the installation
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
bin/heist monitor --role host --config /etc/heist/monitoring.json --environment /root/heiST/backend/.env
```

The timer refreshes one minute after each completed collection, avoiding overlapping
jobs. Remote checks have a 15-second timeout per role; the service has a 180-second
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

**Running challenges → Inspect** now shows the selected instance's VM/agent state,
last keepalive and shared platform sensors. SQL refreshes administrator authority
and resolves the instance's VM IDs before projecting cached `Agent_<vmid>` records.
Other instances' agents are excluded. Missing agents and active agents with
keepalives older than 180 seconds are labelled explicitly. A stale platform receipt
cannot produce current agent or sensor health. Stopped VMs use a warning tone
instead of a false running-VM alarm. The view refreshes every 30 seconds.

The inventory is bounded to 256 matching managed-agent candidates; an incomplete
or ambiguous inventory fails closed. Registration and keepalive metadata establish
the current VM-ID association only. Historical command/packet attribution must
additionally bind immutable instance and assignment IDs and their start/end times;
VM IDs and IPs can be reused. Grafana variables are filters, not access control.
Student event views would need separate ownership enforcement; this release adds
no unrestricted event browser.

## Configure authenticated pipeline probes

The collector reads the existing backend environment for Wazuh API credentials and
its pinned certificate. Set `HEIST_MONITORING_ENVIRONMENT_FILE` there to an existing
absolute path, such as `/etc/heist/monitoring.env`, for additional private settings.
Keep it root-owned, mode0600, outside Git. The declared file participates in the
host checkpoint. Missing credentials produce unknown checks.

Use `MONITORING_HOST`, `GRAFANA_USER`, `GRAFANA_PASSWORD`, `GRAFANA_PORT`,
`CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` and `CLICKHOUSE_HTTPS_PORT`.
Optional `GRAFANA_CA_FILE`/`CLICKHOUSE_CA_FILE` specify trusted CA files. Legacy
leaf pinning uses `GRAFANA_PINNED_CERTIFICATE_FILE` or
`CLICKHOUSE_PINNED_CERTIFICATE_FILE`; obtain and verify leaves through the trusted
infrastructure channel. TLS verification stays enabled and redirects are rejected.
Use dedicated read-only API/database accounts when provisioning monitoring access.

Grafana search checks the six source dashboard titles within the account's view;
an account without access cannot prove dashboards are present. ClickHouse queries
are fixed `SELECT` aggregates over recent `stats` rows in `suricata.*_eve_logs`,
with read-only mode, a three-second execution limit and bounded results. They do
not retrieve addresses, commands or payloads. See the official
[Grafana search API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/api-legacy/folder_dashboard_search/)
and [Wazuh API examples](https://documentation.wazuh.com/current/user-manual/api/api-examples.html).

## Independent watchdog and journal alerts

The off-host observer runs on the archive VM, independently of heiST HTTP/Gunicorn
and the frontend. It reads the bounded private snapshot over pinned SSH, detects
stale/malformed/missing receipts, and requires evidence for critical services across
the host, web, database, monitoring and archive roles, plus Wazuh containers and
database readiness. A fresh host receipt with an unreachable infrastructure VM
still produces a critical failure. Configure all roles before activating it.
Failed checks or unverified critical services produce exit 1 and a failed systemd
job. Unknown end-to-end coverage remains unknown, without becoming a false service
outage. Recovery publishes a new snapshot and the next job exits successfully.
Alerts currently go to the **systemd journal only**, as selected by the operator;
no email/webhook destination is configured or contacted.

Build the standard-library-only artifact from reviewed source:

```sh
python3 tools/build/watchdog.py --output /private/artifacts/watchdog.pyz
```

For a reviewed archive-host installation, copy the artifact to
`/usr/local/lib/heist/watchdog.pyz`, adapt `watchdog.example.json` to the source
host, and install it as root-owned `/etc/heist/watchdog.json` mode0600. Review
`heist-watchdog.service` and `.timer` separately from the source collector units.
They use the existing archive account and systemd-loaded identity, known-host and
configuration credentials; no additional Python package or private-key export is needed.
The key must already support noninteractive SSH. Inspect a manual service run,
then enable its timer. Read alerts with `journalctl -u heist-watchdog.service`;
its receipt is private under `/var/lib/heist-watchdog/status.json`. The observer is
prepared and tested locally, not installed on the production archive host yet.

The packaged-artifact test runs without site-packages or the application and
proves healthy→failed→recovered exit codes using a synthetic SSH source. Live
off-host reachability, reboot, actual source failure and alert recovery still
require the isolated appliance rehearsal before deployment.

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
certificate-verified client and test their data queries. The local Grafana updater
now uses a bounded, certificate-verified session and no longer changes requests
globally. Default passwords were removed. The deployed updater has not been changed.

See the [monitoring acceptance matrix](../testing/MONITORING.md) for the required
rehearsals. Neither these observations nor portable tests certify complete capture
or authorize a production monitoring rollout.
