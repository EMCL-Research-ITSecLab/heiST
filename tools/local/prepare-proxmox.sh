#!/bin/bash
# Run INSIDE the disposable Debian 13 pilot only. Never on the workstation.
set -euo pipefail
test "$(hostname -s)" = heist-pilot
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
test -f /root/pilot-cloud-init-ready
export DEBIAN_FRONTEND=noninteractive
# Cloud-image resolved's stub loses its uplink when networkd is disabled.
if test -L /etc/resolv.conf; then
    unlink /etc/resolv.conf
fi
echo 'nameserver 10.0.2.3' > /etc/resolv.conf
if ! uname -r | grep -q -- '-pve$'; then
    apt-get update
    apt-get install -y wget ca-certificates gnupg ifupdown2
    wget -q https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg \
        -O /usr/share/keyrings/proxmox-archive-keyring.gpg
    echo '136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45  /usr/share/keyrings/proxmox-archive-keyring.gpg' | sha256sum -c -
    cat > /etc/apt/sources.list.d/pve.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
    apt-get update
    echo 'grub-pc grub-pc/install_devices multiselect /dev/vda' | debconf-set-selections
    apt-get install -y proxmox-default-kernel
    # Move management onto the bridge required by the nested hypervisor.
    mkdir -p /etc/cloud/cloud.cfg.d
    echo 'network: {config: disabled}' > /etc/cloud/cloud.cfg.d/99-pilot-network.cfg
    cat > /etc/network/interfaces <<'EOF'
auto lo
iface lo inet loopback
iface ens3 inet manual
auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    gateway 10.0.2.2
    bridge-ports ens3
    bridge-stp off
    bridge-fd 0
EOF
    # Cloud images use systemd-networkd. Disable on next boot, without dropping SSH.
    systemctl mask systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service
    echo 'Kernel installed. Reboot this nested guest, then rerun this script.'
    exit 0
fi
echo 'postfix postfix/main_mailer_type select Local only' | debconf-set-selections
echo 'postfix postfix/mailname string heist-pilot.test' | debconf-set-selections
apt-get update
apt-get install -y proxmox-ve postfix open-iscsi chrony git python3-venv
systemctl is-active pveproxy pvedaemon pve-cluster
test -c /dev/kvm
pveversion -v > /root/pve-package-lock.txt
echo 'Nested Proxmox ready. Configure heiST with directory storage local (not local-lvm).'
echo 'Do not start vulnerable challenge VMs until the outer QEMU is restarted offline.'
