#!/usr/bin/env python3
"""
CTF Layer 1 Monitoring Setup Script
Sets up network monitoring with Suricata, Zeek, and ELK stack for CTF infrastructure
"""

import os
import re
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
IPTABLES_FILE = os.getenv("IPTABLES_FILE","/etc/iptables-backend/iptables.sh")

from monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    run_cmd, run_cmd_with_realtime_output, Timer, time_function, DEBUG_MODE
)

# ==== CONFIGURATION CONSTANTS ====
CHALLENGE_NETWORKS_MASK = "/9"
NETWORK_SIZE = "/24"
PF_RING_VERSION = "9.0.0"
CHALLENGES_ROOT_SUBNET = os.getenv("CHALLENGES_ROOT_SUBNET", "10.128.0.0")
SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
NEW_SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")
MONITORING_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
MONITORING_DNS = os.getenv("MONITORING_DNS", "clickhouse.local")
PROXMOX_IP = os.getenv("PROXMOX_HOST", "10.0.0.1")
WEBSERVER_IP = os.getenv("WEBSERVER_HOST", "10.0.0.101")
DATABASE_IP = os.getenv("DATABASE_HOST", "10.0.0.102")
BACKEND_NETWORK = os.getenv("BACKEND_NETWORK_SUBNET", "10.0.0.0/24")
SURICATA_DIR = Path(os.getenv("SURICATA_FILES_DIR", "/etc/suricata"))
SURICATA_RULES_DIR = Path(os.getenv("SURICATA_RULES_DIR", "/var/lib/suricata/rules"))
CHALLENGE_NETWORKS = CHALLENGES_ROOT_SUBNET + CHALLENGE_NETWORKS_MASK
MONITORING_VPN_INTERFACE = os.getenv("MONITORING_VPN_INTERFACE", "ctf_monitoring")
MONITORING_BACKEND_INTERFACE = os.getenv("BACKEND_NETWORK_DEVICE", "backend")
MONITORING_DMZ_INTERFACE = os.getenv("MONITORING_DMZ_INTERFACE", "dmz_monitoring")
CERT_DIR = os.getenv("SSL_TLS_CERTS_DIR", "/root/heiST/setup/certs")
FULLCHAIN = os.path.join(CERT_DIR, "fullchain.pem")
PRIVKEY = os.path.join(CERT_DIR, "privkey.pem")
VECTOR_SETUP_DIR = os.getenv("VECTOR_FILES_DIR", "/root/heiST/monitoring/vector")
VECTOR_DIR = os.getenv("VECTOR_DIR", "/etc/vector/")
ZEEK_SITE_DIR = Path(os.getenv("ZEEK_SITE_DIR", "/usr/local/zeek/share/zeek/site"))
SURICATA_LOG_DIR = Path(os.getenv("SURICATA_LOG_DIR", "/var/log/suricata"))
PROXMOX_INTERNAL_IP = os.getenv("PROXMOX_INTERNAL_IP", "10.0.3.4")


def parse_arguments():
    """Handle command-line arguments"""
    parser = argparse.ArgumentParser(description="CTF Monitoring Setup Script")
    parser.add_argument('--pf_ring', action='store_true',
                        help='Install PF_RING for high-performance monitoring')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    return parser.parse_args()


@time_function
def install_local_packages():
    """Install required system packages for monitoring"""
    log_section("Installing Local Monitoring Packages")

    debian_version = None
    with open("/etc/os-release") as f:
        for line in f:
            if line.startswith("DEBIAN_VERSION_FULL="):
                debian_version = line.strip().split("=")[1].strip('"').split(".")[0]

    if not debian_version:
        debian_version = "12"



    # Add Zeek repository
    zeek_install_commands = [
        ["apt-get", "install", "-y", "apt-transport-https", "ca-certificates", "curl", "gnupg"],
        ["bash", "-c",
         f"curl -fsSL https://download.opensuse.org/repositories/security:zeek/Debian_{debian_version}/Release.key | "
         "gpg --dearmor -o /etc/apt/trusted.gpg.d/zeek.gpg"],
        ["bash", "-c",
         f'echo "deb [arch=amd64] https://download.opensuse.org/repositories/security:/zeek/Debian_{debian_version}/ /" | tee /etc/apt/sources.list.d/security.zeek.list'],
        ["apt-get", "update"]
    ]

    for cmd in zeek_install_commands:
        try:
            if cmd[0] == "apt-get" and cmd[1] == "install":
                exit_code = run_cmd_with_realtime_output(cmd, check=True)
            elif cmd[0] == "apt-get" and cmd[1] == "update":
                exit_code = run_cmd_with_realtime_output(cmd, check=True)
            else:
                result = run_cmd(cmd, check=True)
        except Exception as e:
            log_warning(f"Zeek repo setup warning: {e}")
            if "zeek" in ' '.join(cmd):
                log_warning("Consider manual installation if this persists: https://zeek.org/get-zeek/")

    # Install base packages
    packages = [
        "zeek",
        "zeekctl",
        "curl",
        "jq",
        "tcpdump",
        "python3-requests",
        "python3-yaml"
    ]

    for package in packages:
        try:
            log_info(f"Installing {package}...")
            exit_code = run_cmd_with_realtime_output(["apt", "install", "-y", package], check=True)
        except Exception as e:
            log_warning(f"Package installation warning for {package}: {e}")
            if package == "zeek":
                log_warning("Trying alternative Zeek installation method...")
                try:
                    exit_code = run_cmd_with_realtime_output(["apt", "install", "-y", "zeek-lts"], check=True)
                except Exception:
                    log_error("Zeek installation failed. You may need to build from source.")

    # Install Suricata
    try:
        install_suricata()
    except Exception as e:
        log_error(f"Error installing Suricata: {e}")

    log_success("Local packages installed")


@time_function
def install_suricata():
    """Install Suricata from source with dependencies"""
    log_section("Installing Suricata from Source")

    packages = [
        "autoconf",
        "automake",
        "build-essential",
        "cargo",
        "cbindgen",
        "libjansson-dev",
        "libpcap-dev",
        "libpcre2-dev",
        "libtool",
        "libyaml-dev",
        "make",
        "pkg-config",
        "zlib1g-dev",
        "libnuma-dev",
        "libdpdk-dev",
        "libcap-ng-dev",
        "libmagic-dev",
        "liblz4-dev",
        "libunwind-dev",
        "libmaxminddb-dev",
        "libnetfilter-queue-dev",
        "libnfnetlink-dev"
    ]

    for package in packages:
        log_info(f"Installing dependency: {package}")
        exit_code = run_cmd_with_realtime_output(["apt", "install", "-y", package], check=True)

    log_info("Installing Rust toolchain...")
    exit_code = run_cmd("curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init", check=True, shell=True)
    run_cmd("chmod +x /tmp/rustup-init", check=True, shell=True)

    env = os.environ.copy()
    env["CARGO_HOME"] = "/root/.cargo"
    env["RUSTUP_HOME"] = "/root/.rustup"

    exit_code = run_cmd_with_realtime_output(["/tmp/rustup-init", "-y", "--no-modify-path"], check=True, env=env)

    cargo_bin = "/root/.cargo/bin"
    os.environ["PATH"] = f"{cargo_bin}:{os.environ['PATH']}"

    result = run_cmd([f"{cargo_bin}/rustup", "--version"], check=True)
    log_debug(f"rustup version: {result.stdout}")

    exit_code = run_cmd_with_realtime_output([f"{cargo_bin}/rustup", "update"], check=True)

    # Build and install Suricata
    log_info("Downloading Suricata source...")
    run_cmd("wget https://www.openinfosecfoundation.org/download/suricata-8.0.0.tar.gz", check=True, shell=True)
    run_cmd("tar -xzvf suricata-8.0.0.tar.gz", check=True, shell=True)

    log_info("Configuring and compiling Suricata (this may take a while)...")
    exit_code = run_cmd_with_realtime_output([
        "sh", "-c",
        "cd suricata-8.0.0 && ./configure --prefix=/usr/ --sysconfdir=/etc --localstatedir=/var --enable-geoip --enable-dpdk --enable-nfqueue && make"
    ], check=True)

    log_info("Installing Suricata...")
    exit_code = run_cmd_with_realtime_output(["sh", "-c", "cd suricata-8.0.0 && make install-full"], check=True)

    log_success("Suricata installed from source")


@time_function
def install_pf_ring(args):
    """Install and configure PF_RING for high-performance packet capture"""
    try:
        log_section("Installing PF_RING")

        log_info("Installing PF_RING dependencies")
        run_cmd(
            'echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" > /etc/apt/sources.list.d/pve-no-subscription.list',
            check=True, shell=True
        )

        exit_code = run_cmd_with_realtime_output([
            "sh", "-c",
            "apt-get update && apt-get install -y build-essential pve-headers-$(uname -r) bison flex libnuma-dev wget"
        ], check=True)

        log_info("Downloading PF_RING")
        run_cmd(
            f"wget https://github.com/ntop/PF_RING/archive/refs/tags/{PF_RING_VERSION}.tar.gz -O /tmp/pfring.tar.gz",
            check=True, shell=True
        )
        run_cmd(f"tar xvzf /tmp/pfring.tar.gz -C /tmp", check=True, shell=True)

        log_info("Compiling and installing PF_RING kernel module")
        os.chdir(f"/tmp/PF_RING-{PF_RING_VERSION}/kernel")

        exit_code = run_cmd_with_realtime_output(["make"], check=True)
        exit_code = run_cmd_with_realtime_output(["make", "install"], check=True)

        log_info("Compiling and installing PF_RING userland tools")
        os.chdir(f"/tmp/PF_RING-{PF_RING_VERSION}/userland")

        exit_code = run_cmd_with_realtime_output(["make"], check=True)
        exit_code = run_cmd_with_realtime_output(["make", "install"], check=True)

        log_info("Loading kernel module")
        run_cmd("modprobe pf_ring transparent_mode=2 min_num_slots=32768 enable_tx_capture=1", check=True, shell=True)

        # Persistent module loading
        with open("/etc/modules-load.d/pfring.conf", "w") as f:
            f.write("pf_ring\n")
        with open("/etc/modprobe.d/pfring.conf", "w") as f:
            f.write("options pf_ring transparent_mode=2 min_num_slots=32768 enable_tx_capture=1\n")

        log_info("Verifying installation")
        run_cmd(["ldconfig"], check=True)
        result = run_cmd("lsmod | grep pf_ring", check=True, shell=True)
        if "pf_ring" not in result.stdout:
            raise Exception("PF_RING kernel module not loaded")

        configure_pf_ring_interface()
        create_network_monitoring_device(MONITORING_VPN_INTERFACE)
        create_network_monitoring_device(MONITORING_DMZ_INTERFACE)
        optimize_system()

        log_success("PF_RING successfully installed and configured")
    except Exception as e:
        log_error(f"PF_RING installation failed: {e}")
        raise


@time_function
def configure_pf_ring_interface():
    """Configure network interfaces for PF_RING"""
    try:
        log_section("Configuring Network Interfaces for PF_RING")

        # Use monitoring interface directly
        real_iface = MONITORING_VPN_INTERFACE
        log_debug(f"Using interface: {real_iface}")

        commands = [
            # Disable NIC offloading
            f"ethtool -K {real_iface} rx off tx off sg off tso off gso off gro off lro off",
            # Increase ring buffers
            f"ethtool -G {real_iface} rx 4096 tx 4096",
            # Set MTU
            f"ip link set {real_iface} mtu 9000",
            # Enable promiscuous mode
            f"ip link set {real_iface} promisc on",
            # Kernel tuning
            "sysctl -w net.core.rmem_max=16777216",
            "sysctl -w net.core.wmem_max=16777216",
            "sysctl -w net.core.netdev_max_backlog=10000",
            "sysctl -w net.core.dev_weight=600",
        ]

        for cmd in commands:
            run_cmd(cmd, check=True, shell=True)

        log_success("Network interfaces configured for PF_RING")
    except Exception as e:
        log_error(f"Interface configuration failed: {e}")
        raise


@time_function
def create_network_monitoring_device(iface):
    """Create network monitoring device and make it persistent"""
    log_info(f"Creating network monitoring device: {iface}")

    # 1. Create and activate it immediately
    commands = [
        f"modprobe ifb",
        f"ip link add {iface} type ifb",
        f"ip link set dev {iface} up"
    ]
    for cmd in commands:
        run_cmd(cmd, check=False, shell=True)

    config_block = f"""
# Virtual IFB device for monitoring
auto {iface}
iface {iface} inet manual
    pre-up modprobe ifb
    pre-up ip link add {iface} type ifb || true
    up ip link set {iface} up
    down ip link set {iface} down
    post-down ip link del {iface} || true
"""
    try:
        with open("/etc/network/interfaces", "a") as f:
            f.write(config_block)
        log_success(f"Added persistent configuration for {iface} to /etc/network/interfaces")
    except Exception:
        log_error(f"Failed to add persistent configuration for {iface}")


@time_function
def set_backend_nfqueue_rules():
    """Set NFQueue rules for backend traffic inspection"""
    log_section("Setting up NFQueue Rules")

    commands = [
        "iptables -I FORWARD -i vmbr0 -o vrt_backend: -j NFQUEUE --queue-num 0 --queue-bypass",
        "iptables -I FORWARD -i vrt_backend: -o vmbr0 -j NFQUEUE --queue-num 0 --queue-bypass"
    ]

    for cmd in commands:
        try:
            run_cmd(cmd, check=True, shell=True)
            try:
                with open(IPTABLES_FILE, "a") as f:
                    f.write(cmd + "\n")
            except Exception as file_err:
                log_warning(f"Failed to write rule to {IPTABLES_FILE}: {file_err}")

        except Exception as e:
            log_warning(f"Failed to execute NFQueue rule: {cmd}")
            log_warning(f"Error: {e}")
            continue

    log_success("NFQueue rules configured")


@time_function
def optimize_system():
    """Apply system-wide optimizations for monitoring performance"""
    try:
        log_section("Applying System Optimizations")

        # Increase file descriptors
        with open("/etc/security/limits.d/ctf-monitoring.conf", "w") as f:
            f.write("* soft nofile 1000000\n* hard nofile 1000000\n")

        # Kernel tuning
        with open("/etc/sysctl.d/99-ctf-monitoring.conf", "w") as f:
            f.write("""net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.core.netdev_max_backlog=10000
net.core.somaxconn=65535
net.ipv4.tcp_max_syn_backlog=20480
vm.swappiness=10
vm.overcommit_memory=1
""")
        run_cmd("sysctl -p /etc/sysctl.d/99-ctf-monitoring.conf", check=True, shell=True)

        # Disable CPU frequency scaling
        log_info("Installing and configuring cpufrequtils...")
        exit_code = run_cmd_with_realtime_output(["apt", "install", "-y", "cpufrequtils"], check=True)
        with open("/etc/default/cpufrequtils", "w") as f:
            f.write('GOVERNOR="performance"\n')
        run_cmd("systemctl restart cpufrequtils", check=True, shell=True)

        log_success("System optimizations applied")
    except Exception as e:
        log_error(f"System optimization failed: {e}")
        raise


@time_function
def setup_suricata_disables():
    """Configure disabled rules for main Suricata instance"""
    log_section("Configuring Suricata Disabled Rules")
    disable_config = """2200121
    """
    with open(f"{SURICATA_DIR}/disable.conf", "w") as f:
        f.write(disable_config)


@time_function
def setup_suricata_dmz_disables():
    """Configure disabled rules for DMZ Suricata instance"""
    disable_config = """2200121
    """
    with open(f"{SURICATA_DIR}/dmz-disable.conf", "w") as f:
        f.write(disable_config)


@time_function
def setup_suricata_backend_disables():
    """Configure disabled rules for backend Suricata instance"""
    disable_config = """2010939
2013504
2200122
2200003
    """
    with open(f"{SURICATA_DIR}/backend-disable.conf", "w") as f:
        f.write(disable_config)


@time_function
def setup_suricata_rules():
    """Download and configure Suricata rules for main monitoring"""
    log_section("Setting up Suricata Rules")

    # Update Suricata rules
    log_info("Downloading and updating Suricata rules...")
    exit_code = run_cmd_with_realtime_output(
        f"suricata-update --disable-conf {SURICATA_DIR}/disable.conf".split(),
        check=True
    )
    run_cmd(f"sed -i 's/^#//' {SURICATA_RULES_DIR}/suricata.rules", check=True, shell=True)

    # Create Lua script for subnet checking
    lua_script = SURICATA_RULES_DIR / "check_diff_subnet.lua"
    lua_script.write_text("""-- Suricata Lua script: alert if source and destination are in different /24 networks within 10.128.0.0/9
function init (args)
    local needs = {}
    needs["packet"] = tostring(true)
    return needs
end

function match(args)
    local src_ip = args["ip_src"]
    local dst_ip = args["ip_dst"]

    if not src_ip or not dst_ip then
        return 0
    end

    -- Convert IP to number and mask to /24
    local src_num = ip_to_number(src_ip)
    local dst_num = ip_to_number(dst_ip)

    if (src_num & 0xFF800000) ~= 0x0A800000 or  -- Check 10.128.0.0/9
       (dst_num & 0xFF800000) ~= 0x0A800000 then
        return 0
    end

    -- Compare /24 prefixes
    return (src_num & 0xFFFFFF00) ~= (dst_num & 0xFFFFFF00) and 1 or 0
end

function ip_to_number(ip_str)
    local o1, o2, o3, o4 = ip_str:match("(%d+)%.(%d+)%.(%d+)%.(%d+)")
    return tonumber(o1) * 0x1000000 + tonumber(o2) * 0x10000 + tonumber(o3) * 0x100 + tonumber(o4)
end
""")

    # Create custom CTF rules
    rules_file = SURICATA_RULES_DIR / "ctf-custom.rules"
    rules_file.parent.mkdir(parents=True, exist_ok=True)

    # Rule templates
    tcp_template = "alert tcp {src} any -> {dst} any (msg:\"{msg}\"; flags:S; threshold:type both,track by_src,count {count},seconds {seconds}; sid:{sid}; priority:{priority}; metadata:policy {metadata};)"
    generic_tcp_template = "alert tcp {src} any -> {dst} any (msg:\"{msg}\"; flags:S; sid:{sid}; priority:{priority}; metadata:policy {metadata};)"

    infrastructure_ips = [PROXMOX_IP, MONITORING_IP, WEBSERVER_IP, DATABASE_IP]

    with rules_file.open("w") as f:
        # Infrastructure access rules
        f.write(tcp_template.format(
            src="any",
            dst=",".join(infrastructure_ips),
            msg="CTF: Infrastructure Access",
            count=5,
            seconds=300,
            sid=9001000,
            priority=1,
            metadata="ctf-infrastructure"
        ) + "\n")

        # HTTP to backend rules
        f.write(generic_tcp_template.format(
            src="any",
            dst=BACKEND_NETWORK,
            msg="CTF: HTTP to Infrastructure",
            sid=9001007,
            priority=2,
            metadata="ctf-infrastructure"
        ) + "\n")

        # Cross-Challenge Network Access
        f.write(
            f"alert tcp {CHALLENGE_NETWORKS} any -> {CHALLENGE_NETWORKS} any (msg:\"CTF: Cross-Challenge /24 Access\"; sid:9002001; lua:check_diff_subnet.lua;)\n")

        # Port scanning detection
        f.write(
            "alert tcp any any -> any any (msg:\"CTF: Rapid Port Hopping\"; flags:S; threshold:type both,track by_src,count 20,seconds 30; sid:9001020; priority:2;)\n")
        f.write(
            "alert tcp any any -> any any (msg:\"CTF: Sequential Port Scan\"; flags:S; threshold:type both, track by_src, count 10, seconds 10; sid:9001021; priority:3;)\n")

        # DNS tunneling detection
        f.write(
            "alert dns any any -> any 53 (msg:\"CTF: DNS Query Volume Spike\"; threshold:type both,track by_src,count 200,seconds 60; sid:9001004; rev:2; priority:2;)\n")
        f.write(
            "alert dns any any -> any 53 (msg:\"CTF: Possible DNS tunneling (long label / b32/b64)\"; dns.query; pcre:\"/(?:[A-Za-z2-7]{40,}|[A-Za-z0-9+/]{40,}=*)\\./R\"; threshold:type both,track by_src,count 10,seconds 60; sid:9001010; rev:2; priority:2;)\n")
        f.write(
            "alert dns any any -> any 53 (msg:\"CTF: DNS TXT record abuse (heuristic)\"; dns.opcode:0; dns.query; content:\"=\"; nocase; content:\".\"; endswith; pcre:\"/^([A-Za-z0-9_\\-]{1,63}\\.){1,10}$/\"; threshold:type both,track by_src,count 15,seconds 60; sid:9001011; rev:3; priority:2;)\n")

    log_success("Suricata rules configured")


@time_function
def setup_suricata_backend_rules():
    """Download and configure Suricata rules for backend monitoring"""
    log_section("Setting up Backend Suricata Rules")

    log_info("Downloading backend Suricata rules...")
    exit_code = run_cmd_with_realtime_output(
        f"suricata-update --disable-conf {SURICATA_DIR}/backend-disable.conf --output {SURICATA_RULES_DIR}/backend".split(),
        check=True
    )
    run_cmd(f"sed -i 's/^#//' {SURICATA_RULES_DIR}/backend/suricata.rules", check=True, shell=True)

    # Add custom backend rule
    backend_custom_path = SURICATA_RULES_DIR / "backend" / "backend-custom.rules"
    custom_rule = 'alert ip $SQL_SERVERS any -> $EXTERNAL_NET any (msg:"SQL server talking to EXTERNAL_NET"; sid:1000001; rev:1; classtype:bad-unknown;)'

    backend_custom_path.write_text(custom_rule + "\n")
    log_debug(f"Custom backend rule written to {backend_custom_path}")

    log_success("Backend Suricata rules configured")


@time_function
def setup_suricata_dmz_rules():
    """Download and configure Suricata rules for DMZ monitoring"""
    log_section("Setting up DMZ Suricata Rules")

    log_info("Downloading DMZ Suricata rules...")
    exit_code = run_cmd_with_realtime_output(
        f"suricata-update --disable-conf {SURICATA_DIR}/dmz-disable.conf --output {SURICATA_RULES_DIR}/dmz".split(),
        check=True
    )
    run_cmd(f"sed -i 's/^#//' {SURICATA_RULES_DIR}/dmz/suricata.rules", check=True, shell=True)

    log_success("DMZ Suricata rules configured")


@time_function
def setup_suricata_config(args):
    """Configure main Suricata instance for VPN monitoring"""
    log_section("Configuring Main Suricata Instance")

    run_cmd(f"sudo mkdir -p {SURICATA_LOG_DIR}/pcap", check=True, shell=True)

    if args.pf_ring:
        interface_config = f"""
# PF_RING configuration
pfring:
  - interface: {MONITORING_VPN_INTERFACE}
    threads: auto
    cluster-id: 99
    cluster-type: cluster_flow
    bypass: yes
    use-mmap: yes
    ring-size: 262144
    block-size: 1048576
    copy-mode: 1
    copy-iface: eth0
"""
    else:
        interface_config = f"""
# Standard af-packet configuration
af-packet:
  - interface: {MONITORING_VPN_INTERFACE}
    cluster-id: 99
    cluster-type: cluster_flow
    threads: auto
    tpacket-v3: yes
    ring-size: 262144
    block-size: 1048576
    defrag: yes
    use-mmap: yes
    mmap-locked: yes
"""

    suricata_config = f"""%YAML 1.1
---
# CTF Suricata Configuration - VPN Monitoring

vars:
  address-groups:
    HOME_NET: "[{CHALLENGE_NETWORKS}]"
    INFRA_NET: "[{BACKEND_NETWORK}]"
    EXTERNAL_NET: any
    HTTP_SERVERS: "$HOME_NET"
    SQL_SERVERS: "$HOME_NET"
    TELNET_SERVERS: "$HOME_NET"
    SMTP_SERVERS: "$HOME_NET"
    DNS_SERVERS: "$HOME_NET"

  port-groups:
    HTTP_PORTS: "[80,8080]"
    SSH_PORTS: "[22]"
    ORACLE_PORTS: any
    SHELLCODE_PORTS: any

default-rule-path: {SURICATA_RULES_DIR}
rule-files:
  - suricata.rules
  - ctf-custom.rules

security:
  lua:
    scripts-dir: {SURICATA_RULES_DIR}
    allow-rules: true
    max-bytes: 500000
    max-instr: 1000000
    max-stack: 1000

{interface_config}

# Logging configuration
outputs:
  - fast:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/fast_vpn.log
      
  - pcap-log:
      enabled: yes
      filename: pcap/suricata_vpn.pcap
      limit: 5000000000

  - eve-log:
      enabled: yes
      filetype: regular
      filename: {SURICATA_LOG_DIR}/eve_vpn.json
      community-id: true
      community-id-seed: 0
      types:
        - alert:
            payload: yes
            payload-buffer-size: 4kb
            payload-printable: yes
            packet: yes
            metadata: yes
            http-body: yes
            http-body-printable: yes
        - anomaly:
            enabled: yes
        - dns:
            query: yes
            answer: yes
        - http:
            extended: yes
        - flow
        - stats:
            enabled: yes
            totals: yes
            threads: yes
            append: yes
            interval: 60
        - netflow:
            enabled: yes
        - ssh:
            enabled: yes
            extended: yes
        - tls:
            extended: yes
            fingerprints: yes
        - files:
            enabled: yes
        - smtp:
            enabled: yes
            extended: yes
        - ftp
        - rdp
        - nfs
        - smb
        - tftp
        - ike
        - dcerpc
        - krb5
        - snmp
        - rfb
        - sip
        - dhcp:
            enabled: yes
        - mqtt:
        - http2

  - http-log:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/http_vpn.log
      append: yes
      extended: yes

  - tcp-data:
      enabled: no
      type: file
      filename: {SURICATA_LOG_DIR}/tcp_vpn.log

  - http-body-data:
      enabled: yes
      type: file
      filename: {SURICATA_LOG_DIR}/http-data_vpn.log

  - stats:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/stats_vpn.log
      append: yes
      totals: yes
      threads: no

# Performance tuning
threading:
  set-cpu-affinity: yes
  cpu-affinity:
    - management-cpu-set:
        cpu: [ "0" ]
    - receive-cpu-set:
        cpu: [ "1" ]
    - worker-cpu-set:
        cpu: [ "all" ]
  detect-thread-ratio: 1.0

# Host and flow settings
host:
  hash-size: 4096
  prealloc: 1000
  memcap: 128mb

flow:
  memcap: 128mb
  hash-size: 65536
  prealloc: 10000
  emergency-recovery: 30

# Stream processing
stream:
  memcap: 64mb
  checksum-validation: yes
  reassembly:
    memcap: 256mb
    depth: 1mb
    toserver-chunk-size: 2560
    toclient-chunk-size: 2560

# Application layer
app-layer:
  protocols:
    https:
      enabled: yes
      libhtp:
        default-body-limit: 10mb    # body capture limit
      request-body-limit: 10mb
      response-body-limit: 10mb
    ftp:
      enabled: yes
    ssh:
      enabled: yes
    smb:
      enabled: yes
    dcerpc:
      enabled: yes
    smtp:
      enabled: yes
    dhcp:
      enabled: yes
    ntp:
      enabled: yes
    tftp:
      enabled: yes
    enip:
      enabled: yes
    nfs:
      enabled: yes
    ikev2:
      enabled: yes
    krb5:
      enabled: yes
    snmp:
      enabled: yes
    sip:
      enabled: yes
    rfb:
      enabled: yes
    mqtt:
      enabled: yes
    dns:
      tcp:
        enabled: yes
        detection-ports:
          dp: 53
      udp:
        enabled: yes
        detection-ports:
          dp: 53
    http:
      enabled: yes
      libhtp:
        default-config:
          personality: IDS
          request-body-limit: 100kb
          response-body-limit: 100kb
    tls:
      enabled: yes
      detection-ports:
        dp: 443
    dnp3:
      enabled: no
    modbus:
      enabled: yes
    rdp:
      enabled: yes
    http2:
      enabled: yes
    imap:
      enabled: yes

# Logging level
logging:
  default-log-level: notice
  outputs:
    - console:
        enabled: yes
    - file:
        enabled: yes
        level: info
        filename: {SURICATA_LOG_DIR}/suricata_vpn.log
"""

    config_file = SURICATA_DIR / "suricata-ctf.yaml"
    config_file.write_text(suricata_config)

    # Test configuration
    log_info("Testing Suricata configuration")
    try:
        result = run_cmd(["suricata", "-T", "-c", str(config_file)], check=True)
        log_success("Suricata configuration test successful")
        if result.stdout and DEBUG_MODE:
            log_debug(result.stdout)
    except Exception as e:
        log_error("Suricata configuration test failed")
        raise Exception("Suricata configuration test failed")


@time_function
def setup_suricata_backend_config():
    """Configure Suricata for backend monitoring using NFQUEUE"""
    log_section("Configuring Backend Suricata Instance")

    suricata_config = f"""%YAML 1.1
---
# CTF Suricata Configuration - Backend Monitoring (NFQUEUE Inline)

vars:
  address-groups:
    HOME_NET: "[{BACKEND_NETWORK}]"
    EXTERNAL_NET: "!$HOME_NET"
    HTTP_SERVERS: "[{WEBSERVER_IP},{MONITORING_IP}]"
    SQL_SERVERS: "{DATABASE_IP}"
    TELNET_SERVERS: "$HOME_NET"
    SMTP_SERVERS: "$HOME_NET"
    DNS_SERVERS: "$HOME_NET"

  port-groups:
    HTTP_PORTS: "[80,8080,3000,9090,8123,9100]"
    SSH_PORTS: "[22]"
    ORACLE_PORTS: any
    SHELLCODE_PORTS: any

default-rule-path: {SURICATA_RULES_DIR}/backend
rule-files:
  - suricata.rules
  - backend-custom.rules

security:
  lua:
    scripts-dir: {SURICATA_RULES_DIR}
    allow-rules: true
    max-bytes: 500000
    max-instr: 1000000
    max-stack: 1000

# NFQUEUE configuration for inline monitoring
nfqueue:
  - id: 0
    fail-open: no
    bypass: no
    copy-mode: ips

# Logging configuration
outputs:
  - fast:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/fast_backend.log

  - pcap-log:
      enabled: yes
      filename: pcap/suricata_backend.pcap
      limit: 5000000000

  - eve-log:
      enabled: yes
      filetype: regular
      filename: {SURICATA_LOG_DIR}/eve_backend.json
      community-id: true
      community-id-seed: 0
      types:
        - alert:
            payload: yes
            payload-buffer-size: 4kb
            payload-printable: yes
            packet: yes
            metadata: yes
            http-body: yes
            http-body-printable: yes
        - anomaly:
            enabled: yes
        - dns:
            query: yes
            answer: yes
        - http:
            extended: yes
        - flow
        - stats:
            enabled: yes
            totals: yes
            threads: yes
            append: yes
            interval: 60
        - netflow:
            enabled: yes
        - ssh:
            enabled: yes
            extended: yes
        - tls:
            extended: yes
            fingerprints: yes
        - files:
            enabled: yes
        - smtp:
            enabled: yes
            extended: yes
        - ftp
        - rdp
        - nfs
        - smb
        - tftp
        - ike
        - dcerpc
        - krb5
        - snmp
        - rfb
        - sip
        - dhcp:
            enabled: yes
        - mqtt:
        - http2

  - http-log:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/http_backend.log
      append: yes
      extended: yes

  - tcp-data:
      enabled: no
      type: file
      filename: {SURICATA_LOG_DIR}/tcp_backend.log

  - http-body-data:
      enabled: yes
      type: file
      filename: {SURICATA_LOG_DIR}/http-data_backend.log

  - stats:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/stats_backend.log
      append: yes
      totals: yes
      threads: no

# Performance tuning
threading:
  set-cpu-affinity: yes
  cpu-affinity:
    - management-cpu-set:
        cpu: [ "0" ]
    - receive-cpu-set:
        cpu: [ "1" ]
    - worker-cpu-set:
        cpu: [ "all" ]
  detect-thread-ratio: 1.0

# Host and flow settings
host:
  hash-size: 4096
  prealloc: 1000
  memcap: 128mb

flow:
  memcap: 128mb
  hash-size: 65536
  prealloc: 10000
  emergency-recovery: 30

# Stream processing
stream:
  memcap: 64mb
  checksum-validation: yes
  reassembly:
    memcap: 256mb
    depth: 1mb
    toserver-chunk-size: 2560
    toclient-chunk-size: 2560

# Application layer
app-layer:
  protocols:
    https:
      enabled: yes
      libhtp:
        default-body-limit: 10mb
      request-body-limit: 10mb
      response-body-limit: 10mb
    ftp:
      enabled: yes
    ssh:
      enabled: yes
    smb:
      enabled: yes
    dcerpc:
      enabled: yes
    smtp:
      enabled: yes
    dhcp:
      enabled: yes
    ntp:
      enabled: yes
    tftp:
      enabled: yes
    enip:
      enabled: yes
    nfs:
      enabled: yes
    ikev2:
      enabled: yes
    krb5:
      enabled: yes
    snmp:
      enabled: yes
    sip:
      enabled: yes
    rfb:
      enabled: yes
    mqtt:
      enabled: yes
    dns:
      tcp:
        enabled: yes
        detection-ports:
          dp: 53
      udp:
        enabled: yes
        detection-ports:
          dp: 53
    http:
      enabled: yes
      libhtp:
        default-config:
          personality: IDS
          request-body-limit: 100kb
          response-body-limit: 100kb
    tls:
      enabled: yes
      detection-ports:
        dp: 443
    dnp3:
      enabled: no
    modbus:
      enabled: yes
    rdp:
      enabled: yes
    http2:
      enabled: yes
    imap:
      enabled: yes

# Logging level
logging:
  default-log-level: notice
  outputs:
    - console:
        enabled: yes
    - file:
        enabled: yes
        level: info
        filename: {SURICATA_LOG_DIR}/suricata_backend.log
"""

    config_file = SURICATA_DIR / "suricata-backend.yaml"
    config_file.write_text(suricata_config)

    log_info("Testing backend Suricata configuration")
    try:
        result = run_cmd(["suricata", "-T", "-c", str(config_file)], check=True)
        log_success("Suricata configuration test successful")
        if result.stdout and DEBUG_MODE:
            log_debug(result.stdout)
    except Exception as e:
        log_error("Backend Suricata configuration test failed")
        raise Exception("Backend Suricata configuration test failed")


@time_function
def setup_suricata_dmz_config(args):
    """Configure Suricata for DMZ monitoring"""
    log_section("Configuring DMZ Suricata Instance")

    if args.pf_ring:
        interface_config = f"""
# PF_RING configuration
pfring:
  - interface: {MONITORING_DMZ_INTERFACE}
    threads: auto
    cluster-id: 99
    cluster-type: cluster_flow
    bypass: yes
    use-mmap: yes
    ring-size: 262144
    block-size: 1048576
    copy-mode: 1
    copy-iface: eth0
"""
    else:
        interface_config = f"""
# Standard af-packet configuration
af-packet:
  - interface: {MONITORING_DMZ_INTERFACE}
    cluster-id: 99
    cluster-type: cluster_flow
    threads: auto
    tpacket-v3: yes
    ring-size: 262144
    block-size: 1048576
    defrag: yes
    use-mmap: yes
    mmap-locked: yes
"""

    suricata_config = f"""%YAML 1.1
---
# CTF Suricata Configuration - DMZ Monitoring

vars:
  address-groups:
    HOME_NET: "!$EXTERNAL_NET"
    EXTERNAL_NET: "[{CHALLENGE_NETWORKS}]"
    HTTP_SERVERS: "$HOME_NET"
    SQL_SERVERS: "$HOME_NET"
    TELNET_SERVERS: "$HOME_NET"
    SMTP_SERVERS: "$HOME_NET"
    DNS_SERVERS: "$HOME_NET"

  port-groups:
    HTTP_PORTS: "[80,8080]"
    SSH_PORTS: "[22]"
    ORACLE_PORTS: any
    SHELLCODE_PORTS: any

default-rule-path: {SURICATA_RULES_DIR}/dmz
rule-files:
  - suricata.rules

security:
  lua:
    scripts-dir: {SURICATA_RULES_DIR}
    allow-rules: true
    max-bytes: 500000
    max-instr: 1000000
    max-stack: 1000

{interface_config}

# Logging configuration
outputs:
  - fast:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/fast_dmz.log
      
  - pcap-log:
      enabled: yes
      filename: pcap/suricata_dmz.pcap
      limit: 5000000000

  - eve-log:
      enabled: yes
      filetype: regular
      filename: {SURICATA_LOG_DIR}/eve_dmz.json
      community-id: true
      community-id-seed: 0
      types:
        - alert:
            payload: yes
            payload-buffer-size: 4kb
            payload-printable: yes
            packet: yes
            metadata: yes
            http-body: yes
            http-body-printable: yes
        - anomaly:
            enabled: yes
        - dns:
            query: yes
            answer: yes
        - http:
            extended: yes
        - flow
        - stats:
            enabled: yes
            totals: yes
            threads: yes
            append: yes
            interval: 60
        - netflow:
            enabled: yes
        - ssh:
            enabled: yes
            extended: yes
        - tls:
            extended: yes
            fingerprints: yes
        - files:
            enabled: yes
        - smtp:
            enabled: yes
            extended: yes
        - ftp
        - rdp
        - nfs
        - smb
        - tftp
        - ike
        - dcerpc
        - krb5
        - snmp
        - rfb
        - sip
        - dhcp:
            enabled: yes
        - mqtt:
        - http2

  - http-log:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/http_dmz.log
      append: yes
      extended: yes

  - tcp-data:
      enabled: no
      type: file
      filename: {SURICATA_LOG_DIR}/tcp_dmz.log

  - http-body-data:
      enabled: yes
      type: file
      filename: {SURICATA_LOG_DIR}/http-data_dmz.log

  - stats:
      enabled: yes
      filename: {SURICATA_LOG_DIR}/stats_dmz.log
      append: yes
      totals: yes
      threads: no


# Performance tuning
threading:
  set-cpu-affinity: yes
  cpu-affinity:
    - management-cpu-set:
        cpu: [ "0" ]
    - receive-cpu-set:
        cpu: [ "1" ]
    - worker-cpu-set:
        cpu: [ "all" ]
  detect-thread-ratio: 1.0

# Host and flow settings
host:
  hash-size: 4096
  prealloc: 1000
  memcap: 128mb

flow:
  memcap: 128mb
  hash-size: 65536
  prealloc: 10000
  emergency-recovery: 30

# Stream processing
stream:
  memcap: 64mb
  checksum-validation: yes
  reassembly:
    memcap: 256mb
    depth: 1mb
    toserver-chunk-size: 2560
    toclient-chunk-size: 2560

# Application layer
app-layer:
  protocols:
    https:
      enabled: yes
      libhtp:
        default-body-limit: 10mb    # body capture limit
      request-body-limit: 10mb
      response-body-limit: 10mb
    ftp:
      enabled: yes
    ssh:
      enabled: yes
    smb:
      enabled: yes
    dcerpc:
      enabled: yes
    smtp:
      enabled: yes
    dhcp:
      enabled: yes
    ntp:
      enabled: yes
    tftp:
      enabled: yes
    enip:
      enabled: yes
    nfs:
      enabled: yes
    ikev2:
      enabled: yes
    krb5:
      enabled: yes
    snmp:
      enabled: yes
    sip:
      enabled: yes
    rfb:
      enabled: yes
    mqtt:
      enabled: yes
    dns:
      tcp:
        enabled: yes
        detection-ports:
          dp: 53
      udp:
        enabled: yes
        detection-ports:
          dp: 53
    http:
      enabled: yes
      libhtp:
        default-config:
          personality: IDS
          request-body-limit: 100kb
          response-body-limit: 100kb
    tls:
      enabled: yes
      detection-ports:
        dp: 443
    dnp3:
      enabled: no
    modbus:
      enabled: yes
    rdp:
      enabled: yes
    http2:
      enabled: yes
    imap:
      enabled: yes

# Logging level
logging:
  default-log-level: notice
  outputs:
    - console:
        enabled: yes
    - file:
        enabled: yes
        level: info
        filename: {SURICATA_LOG_DIR}/suricata_dmz.log
"""

    config_file = SURICATA_DIR / "suricata-dmz.yaml"
    config_file.write_text(suricata_config)

    log_info("Testing DMZ Suricata configuration")
    try:
        result = run_cmd(["suricata", "-T", "-c", str(config_file)], check=True)
        log_success("Suricata configuration test successful")
        if result.stdout and DEBUG_MODE:
            log_debug(result.stdout)
    except Exception as e:
        log_error("DMZ Suricata configuration test failed")
        raise Exception("DMZ Suricata configuration test failed")


@time_function
def setup_zeek(args):
    """Configure Zeek for advanced CTF network analysis"""
    log_section("Configuring Zeek")

    zeek_site_config = f"""
# CTF Zeek Configuration - Enhanced Network Monitoring
@load base/frameworks/notice
@load base/frameworks/sumstats
@load base/protocols/dns
@load base/protocols/conn
@load base/protocols/http
@load base/protocols/ftp
@load base/protocols/ssh
@load base/protocols/ssl

# Load specific policy scripts
@load policy/protocols/conn/known-hosts.zeek
@load policy/protocols/conn/known-services.zeek

redef LogAscii::use_json = T;
redef ignore_checksums = T;
redef tcp_inactivity_timeout = 60 min;
redef udp_inactivity_timeout = 60 min;

# Ensure all analyzers stay enabled for maximum protocol detection
redef Analyzer::disable_all = F;

module CTF;

export {{
    redef enum Notice::Type += {{
        CTF::DNSTunnel,
        CTF::DNSHighEntropy,
        CTF::PortHopping,
        CTF::SuspiciousSubdomains,
        CTF::HexEncodedDomain,
        CTF::PossibleC2
    }};

    global port_seen: table[addr] of set[port] &create_expire=10min;
    global dns_short_queries: table[addr] of count &default=0 &write_expire=1min;
}}

# Enhanced DNS monitoring and detection rules
event dns_request(c: connection, msg: dns_msg, query: string, qtype: count, qclass: count)
{{
    # Track query rate (SumStats)
    SumStats::observe("dns.query.count", 
                     SumStats::Key($host=c$id$orig_h), 
                     SumStats::Observation($num=1));

    # Short query detection (common in DNS tunneling)
    if (|query| < 4) {{
        ++dns_short_queries[c$id$orig_h];
        if (dns_short_queries[c$id$orig_h] > 50) {{
            NOTICE([$note=CTF::DNSTunnel,
                   $msg=fmt("Excessive short DNS queries from %s (%d)", 
                          c$id$orig_h, dns_short_queries[c$id$orig_h]),
                   $src=c$id$orig_h]);
        }}
    }}

    # High entropy detection - Zeek-compatible regex
    if (|query| >= 40) {{
        # Check for long strings of base64/base32-like characters
        if (/[A-Za-z0-9+\/=]{{40,}}/ in query || /[A-Za-z2-7]{{40,}}/ in query) {{
            NOTICE([$note=CTF::DNSHighEntropy,
                   $msg=fmt("High entropy DNS query: %s", query),
                   $conn=c]);
        }}
    }}

    # Multi-level subdomain detection
    local subdomains = split_string(query, /\./);
    if (|subdomains| > 6) {{
        NOTICE([$note=CTF::SuspiciousSubdomains,
               $msg=fmt("Multi-level DNS (%d): %s", |subdomains|, query),
               $conn=c]);
    }}

    # Hex/IP encoded detection
    if (/^[0-9a-f]{{8,}}\./ in query || /[0-9]{{1,3}}\.[0-9]{{1,3}}\.[0-9]{{1,3}}\.[0-9]{{1,3}}\./ in query) {{
        NOTICE([$note=CTF::HexEncodedDomain,
               $msg=fmt("Hex/IP encoded domain: %s", query),
               $conn=c]);
    }}
}}

# Port scanning detection
event connection_established(c: connection)
{{
    local src = c$id$orig_h;
    local dst_port = c$id$resp_p;

    if (src !in port_seen) {{
        port_seen[src] = set();
    }}

    add port_seen[src][dst_port];

    if (|port_seen[src]| > 20) {{
        NOTICE([$note=CTF::PortHopping,
               $msg=fmt("Port scanning detected from %s (%d ports)", 
                       src, |port_seen[src]|),
               $conn=c]);
    }}
}}

# C2 traffic detection
event connection_state_remove(c: connection)
{{
    # Detect beaconing behavior
    if (c$duration > 5min && c$orig$size < 100 && c$resp$size > 1024) {{
        NOTICE([$note=CTF::PossibleC2,
               $msg=fmt("Potential C2 traffic: %s:%d -> %s:%d (%.1f sec interval)",
                      c$id$orig_h, c$id$orig_p,
                      c$id$resp_h, c$id$resp_p,
                      c$duration),
               $conn=c]);
    }}
}}

# Initialize SumStats and register common CTF ports
event zeek_init()
{{
    # Register additional common CTF ports for guaranteed protocol detection
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 80/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 8000/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 8080/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 8888/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 3000/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 5000/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_HTTP, 31337/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_SSH, 22/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_SSH, 2222/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_FTP, 21/tcp);
    Analyzer::register_for_port(Analyzer::ANALYZER_FTP, 2121/tcp);

    # DNS query tracking
    local dns_reducer = SumStats::Reducer(
        $stream="dns.query.count",
        $apply=set(SumStats::SUM, SumStats::HLL_UNIQUE));

    SumStats::create([
        $name="ctf-dns-tracker",
        $epoch=60sec,
        $reducers=set(dns_reducer),
        $threshold_val(key: SumStats::Key, result: SumStats::Result) = {{
            return result["dns.query.count"]$sum;
        }},
        $threshold=100.0,
        $threshold_crossed(key: SumStats::Key, result: SumStats::Result) = {{
            NOTICE([$note=CTF::DNSTunnel,
                   $msg=fmt("DNS query flood from %s (%d total, %d unique)",
                          key$host, 
                          result["dns.query.count"]$sum,
                          result["dns.query.count"]$hll_unique),
                   $src=key$host]);
        }}
    ]);
}}
"""

    try:
        zeek_site_dir = ZEEK_SITE_DIR
        zeek_site_dir.mkdir(parents=True, exist_ok=True)

        # Write CTF-specific configuration
        (zeek_site_dir / "ctf-monitoring.zeek").write_text(zeek_site_config)

        # Configure node for monitoring interface
        node_cfg_path = Path("/opt/zeek/etc/node.cfg")
        if args.pf_ring:
            node_config = f"""
[manager]
type=manager
host=localhost

[proxy-1]
type=proxy
host=localhost

[zeek]
type=worker
host=localhost
interface={MONITORING_VPN_INTERFACE}
lb_method=pf_ring
lb_procs=5
pin_cpus=0,1
"""
        else:
            node_config = f"""
[zeek]
type=standalone
host=localhost
interface={MONITORING_VPN_INTERFACE}
"""

        node_cfg_path.write_text(node_config)

        # Add to local.zeek
        local_zeek = zeek_site_dir / "local.zeek"
        if not local_zeek.exists():
            local_zeek.write_text('@load ./ctf-monitoring.zeek\n')
        else:
            with local_zeek.open("a") as f:
                f.write("\n@load ./ctf-monitoring.zeek\n")

        log_info("Configuring Zeek daily log rotation with gzip using sed...")

        zeekctl_cfg = "/opt/zeek/etc/zeekctl.cfg"

        def set_sed(key, value):
            # Replace if exists
            run_cmd(
                f"sed -i 's|^{key}.*|{key} = {value}|' {zeekctl_cfg}",
                shell=True, check=True
            )
            # Append if missing
            run_cmd(
                f"grep -q '^{key}' {zeekctl_cfg} || echo '{key} = {value}' >> {zeekctl_cfg}",
                shell=True, check=True
            )

        # Apply log rotation settings
        set_sed("LogRotationInterval", "86400")
        set_sed("CompressLogs", "true")
        set_sed("LogRetentionInterval", "90d")

        log_info("Validating Zeek configuration...")
        exit_code = run_cmd_with_realtime_output("/opt/zeek/bin/zeekctl check".split(), check=True)

        log_info("Installing Zeek configuration...")
        exit_code = run_cmd_with_realtime_output("/opt/zeek/bin/zeekctl install".split(), check=True)

        log_success("Zeek CTF monitoring configuration deployed with daily rotation and gzip compression")

    except Exception as e:
        log_error(f"Error configuring Zeek: {str(e)}")
        raise


@time_function
def create_ssl():
    """Create self-signed certificates for monitoring services"""
    log_section("Creating SSL Certificates")

    os.makedirs(CERT_DIR, exist_ok=True)

    # Generate certificate with proper SAN
    san = f"IP:{MONITORING_IP},IP:127.0.0.1,IP:{PROXMOX_INTERNAL_IP},DNS:{MONITORING_DNS}"

    cmd = [
        "openssl", "req",
        "-x509",
        "-nodes",
        "-days", "365",
        "-newkey", "rsa:2048",
        "-keyout", PRIVKEY,
        "-out", FULLCHAIN,
        "-subj", "/C=US/ST=NewYork/L=NYC/O=MyOrg/OU=IT/CN=clickhouse.local",
        "-addext", f"subjectAltName={san}"
    ]

    log_info(f"Generating self-signed certificate in {CERT_DIR}")

    try:
        run_cmd(cmd, check=True)
        # Set restrictive permissions
        os.chmod(FULLCHAIN, 0o640)
        os.chmod(PRIVKEY, 0o640)
        log_success("Certificates created successfully")
        log_debug(f"fullchain.pem: {FULLCHAIN}")
        log_debug(f"privkey.pem: {PRIVKEY}")
    except Exception as e:
        log_error(f"Failed to generate certificates: {e}")


@time_function
def setup_vector():
    """Install and configure Vector for log aggregation"""
    log_section("Setting up Vector")

    vector_commands = [
        "curl -L https://setup.vector.dev | bash",
        "apt-get update",
        "apt-get install -y vector",
        f"cp -r {VECTOR_SETUP_DIR}/. {VECTOR_DIR}/",
        f"{sys.executable} -m monitoring.vector.configure_vector"
    ]

    for cmd in vector_commands:
        exit_code = run_cmd_with_realtime_output(cmd, shell=True, check=True)

    log_info("Set Vector Checkpoint Permissions")
    commands = [
        "mkdir -p /var/lib/vector",
        "chown -R vector:vector /var/lib/vector",
        "chmod 755 /var/lib/vector"
    ]

    for cmd in commands:
        exit_code = run_cmd_with_realtime_output(cmd, shell=True, check=True)

    log_success("Vector configured")


@time_function
def main():
    """Main execution function"""
    global DEBUG_MODE

    args = parse_arguments()
    DEBUG_MODE = args.debug

    try:
        with Timer():
            log_section("Starting CTF Monitoring Setup")

            log_info("Installing local monitoring packages")
            install_local_packages()

            if args.pf_ring:
                log_info("Installing PF_RING for high-performance monitoring")
                install_pf_ring(args)
            else:
                log_info("Setting up standard network monitoring interfaces")
                create_network_monitoring_device(MONITORING_VPN_INTERFACE)
                create_network_monitoring_device(MONITORING_DMZ_INTERFACE)
                set_backend_nfqueue_rules()

            log_info("Configuring Suricata disabled rules")
            setup_suricata_disables()
            setup_suricata_backend_disables()
            setup_suricata_dmz_disables()

            log_info("Setting up Suricata rules")
            setup_suricata_rules()
            setup_suricata_dmz_rules()
            setup_suricata_backend_rules()

            log_info("Configuring Suricata instances")
            setup_suricata_config(args)
            setup_suricata_dmz_config(args)
            setup_suricata_backend_config()

            log_info("Creating SSL certificates")
            create_ssl()

            log_info("Configuring Zeek")
            setup_zeek(args)

            log_info("Installing and configuring Vector")
            setup_vector()

        log_success("CTF monitoring setup completed successfully")

    except Exception as e:
        log_error(f"CTF monitoring setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()