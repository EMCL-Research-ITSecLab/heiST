# Challenge VPN transport

The host must allow each owner to query the assigned edge resolver over both
UDP and TCP port 53. Challenge launch installs the owner-specific DNS chain;
stop and teardown revoke it. This does not expose other students' resolvers.

## TLS connections stall after TCP connects

Check DNS, then use a bounded request with the CA belonging to the deployed
images:

```sh
curl --connect-timeout 5 --max-time 15 --cacert ./lab01-ca.crt \
  -v https://portal.ldap.heist.test/
```

If headers show retransmitted large TCP segments while smaller segments arrive,
check the VPN path's packet-size limit. An active service and a TCP handshake do
not prove that TLS or LDAP data can traverse that path. Do not disable TLS
verification or replace the deployed lab CA with a different build's CA.

The transport helper limits advertised TCP MSS to 1100 for forwarded IPv4
connections between the heiST VPN and challenge address ranges. It changes both
SYN directions, preserves lower advertisements and leaves access filtering
unchanged. It affects new TCP connections, including existing VPN sessions;
there is no OpenVPN or challenge restart. UDP applications remain subject to
their own packet sizes.

Install from the reviewed source checkout on the Proxmox host:

```sh
install -D -m 0644 heist/infrastructure/network/vpn_transport.py \
  /usr/local/lib/heist/vpn_transport.py
install -m 0644 deploy/vpn/systemd/heist-vpn-transport.service \
  /etc/systemd/system/heist-vpn-transport.service
systemd-analyze verify /etc/systemd/system/heist-vpn-transport.service
systemctl daemon-reload
systemctl enable --now heist-vpn-transport.service
systemctl status --no-pager heist-vpn-transport.service
iptables -t mangle -vnL HEIST_VPN_MSS
```

The enabled oneshot unit reinstalls its owned rules at boot. If another tool
flushes the mangle table, restart this unit afterwards. Do not restore an entire
saved firewall table over current per-student rules.

Rollback this helper with `systemctl disable --now heist-vpn-transport.service`.
That removes only its chain and jumps. Preserve the helper file until the unit
has stopped. The isolated `tests.test_vpn_transport` regression reproduces a
bidirectional size black hole, verifies a CA-validated HTTPS upload and response,
checks repeated application, and verifies removal restores the failure.

## Lab DNS/DHCP service ownership

Each challenge dnsmasq runs in its own transient `heist-dnsmasq-vrt….service`
unit. Restarting the API or pool manager must not stop these units. Merely
forking or creating a new process session does not escape a systemd cgroup.
The unit uses the existing per-bridge configuration, lease and log files; it
has no restart policy so teardown cannot resurrect a removed network. Startup
waits for the daemon's PID file. Teardown still validates process identity and
uses a PID descriptor before signalling the owned daemon.

After an update, verify DNS replies on assigned resolvers as well as backend
health. A running API does not prove that a lab's DHCP or DNS is available.
Inspect `/proc/PID/cgroup` to confirm a daemon belongs to its own unit rather
than `backend.service` or `pool_manager.service`.
