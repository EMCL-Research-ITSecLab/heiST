import hashlib
import random
import string

import requests
from dotenv import load_dotenv
import os
from proxmoxer import ProxmoxAPI
import subprocess
import datetime
import sys
import re
import time
import psycopg2

from backend.subnet_calculations import nth_challenge_subnet, nth_vpn_static_ip

load_dotenv()

APT_LOCK_TIMEOUT = os.getenv("APT_LOCK_TIMEOUT", "300")


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROXMOX_HOST = os.getenv("PROXMOX_HOST", "10.0.0.1")
PROXMOX_USER = os.getenv("PROXMOX_USER", "root@pam")
PROXMOX_PASSWORD = os.getenv("PROXMOX_PASSWORD")
PROXMOX_PORT = os.getenv("PROXMOX_PORT", "8006")
BACKEND_PORT = os.getenv("BACKEND_PORT", "8000")
PROXMOX_INTERNAL_IP = os.getenv("PROXMOX_INTERNAL_IP", "10.0.3.4")
PROXMOX_EXTERNAL_IP = os.getenv("PROXMOX_EXTERNAL_IP", "10.0.3.4")
PROXMOX_HOSTNAME = os.getenv("PROXMOX_HOSTNAME", "pve")

UBUNTU_BASE_SERVER_URL = os.getenv("UBUNTU_BASE_SERVER_URL")

DATABASE_FILES_DIR = os.getenv("DATABASE_FILES_DIR", "/root/heiST/database")
DATABASE_NAME = os.getenv("DATABASE_NAME", "heist")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
DATABASE_HOST = os.getenv("DATABASE_HOST", "10.0.0.102")

WEBSERVER_FILES_DIR = os.getenv("WEBSERVER_FILES_DIR", "/root/heiST/webserver")
WEBSERVER_USER = os.getenv("WEBSERVER_USER", "www-data")
WEBSERVER_GROUP = os.getenv("WEBSERVER_GROUP", "www-data")
WEBSERVER_ROOT = os.getenv("WEBSERVER_ROOT", "/var/www/html")
WEBSERVER_HOST = os.getenv("WEBSERVER_HOST", "10.0.0.101")
WEBSERVER_HTTP_PORT = os.getenv("WEBSERVER_HTTP_PORT", "80")
WEBSERVER_HTTPS_PORT = os.getenv("WEBSERVER_HTTPS_PORT", "443")

BACKEND_FILES_DIR = os.getenv("BACKEND_FILES_DIR", "/root/heiST/backend")

OPENVPN_SUBNET = os.getenv("OPENVPN_SUBNET", "10.64.0.0/10")
OPENVPN_SERVER_IP = os.getenv("OPENVPN_SERVER_IP", "10.64.0.1")

BACKEND_NETWORK_SUBNET = os.getenv("BACKEND_NETWORK_SUBNET", "10.0.0.1/24")
BACKEND_NETWORK_ROUTER = os.getenv("BACKEND_NETWORK_ROUTER", "10.0.0.1")
BACKEND_NETWORK_DEVICE = os.getenv("BACKEND_NETWORK_DEVICE", "vrt_backend")
BACKEND_NETWORK_HOST_MIN = os.getenv("BACKEND_NETWORK_HOST_MIN", "10.0.0.2")
BACKEND_NETWORK_HOST_MAX = os.getenv("BACKEND_NETWORK_HOST_MAX", "10.0.0.254")

DATABASE_MAC_ADDRESS = os.getenv("DATABASE_MAC_ADDRESS", "0E:00:00:00:00:01")
WEBSERVER_MAC_ADDRESS = os.getenv("WEBSERVER_MAC_ADDRESS", "0E:00:00:00:00:02")

WEBSITE_ADMIN_USER = os.getenv("WEBSITE_ADMIN_USER", "admin")
WEBSITE_ADMIN_PASSWORD = os.getenv("WEBSITE_ADMIN_PASSWORD")

SYSTEMD_PATH = "/etc/systemd/system"
DNSMASQ_SERVICE_PATH = os.path.join(SYSTEMD_PATH, "dnsmasq-backend.service")
IPTABLES_SERVICE_PATH = os.path.join(SYSTEMD_PATH, "iptables-backend.service")

BACKEND_CERTIFICATE_DIR = os.path.join(BACKEND_FILES_DIR, "certificates")
BACKEND_CERTIFICATE_FILE = os.path.join(BACKEND_CERTIFICATE_DIR, "backend.crt")
BACKEND_CERTIFICATE_KEY_FILE = os.path.join(BACKEND_CERTIFICATE_DIR, "backend.key")


CHALLENGES_ROOT_SUBNET = os.getenv("CHALLENGES_ROOT_SUBNET", "10.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK = os.getenv("CHALLENGES_ROOT_SUBNET_MASK", "255.128.0.0")

TESTING_FILES_DIR = os.path.join(BACKEND_FILES_DIR, "tests", "utils")
TESTING_DATABASE_BASE_DIR = os.getenv("TESTING_DATABASE_BASE_DIR", "/tmp/pg_test_base")
TESTING_DATABASE_NAME = os.getenv("TESTING_DATABASE_NAME", "heist")
TESTING_DATABASE_USER = os.getenv("TESTING_DATABASE_USER", "postgres")
TESTING_DATABASE_PASSWORD = os.getenv("TESTING_DATABASE_PASSWORD")
TESTING_DATABASE_PORT = os.getenv("TESTING_DATABASE_PORT", "5432")
TESTING_DATABASE_HOST = os.getenv("TESTING_DATABASE_HOST", "localhost")

WEBSERVER_DATABASE_USER = os.getenv("WEBSERVER_DATABASE_USER", "api_user")
WEBSERVER_DATABASE_PASSWORD = os.getenv("WEBSERVER_DATABASE_PASSWORD")

MONITORING_VPN_INTERFACE = os.getenv("MONITORING_VPN_INTERFACE", "ctf_monitoring")
MONITORING_DMZ_INTERFACE = os.getenv("MONITORING_DMZ_INTERFACE", "dmz_monitoring")
MONITORING_HOST = os.getenv("MONITORING_HOST", "10.0.0.103")
MONITORING_VM_ID = os.getenv("MONITORING_VM_ID", "9000")
WAZUH_PORT = os.getenv("WAZUH_API_PORT", "55000")
WAZUH_USER = os.getenv("WAZUH_API_USER", "wazuh-wui")
WAZUH_PASSWORD = os.getenv("WAZUH_API_PASSWORD", "MyS3cr37P450r.*-")
WAZUH_ENROLLMENT_PASSWORD = os.getenv("WAZUH_ENROLLMENT_PASSWORD", "")
WAZUH_NETWORK_DEVICE = os.getenv("WAZUH_NETWORK_DEVICE", BACKEND_NETWORK_DEVICE)

BACKEND_AUTHENTICATION_TOKEN = hashlib.sha256(os.urandom(64)).hexdigest()


REUSE_DOWNLOADED_OVA = True

time_start = datetime.datetime.now()


def setup():
    """
    Setup the environment.
    """

    print("Starting setup")
    print("\nVerifying existence of required directories")
    if not os.path.exists(DATABASE_FILES_DIR):
        raise FileNotFoundError(f"Database files directory not found: {DATABASE_FILES_DIR}")

    if not os.path.exists(WEBSERVER_FILES_DIR):
        raise FileNotFoundError(f"Webserver files directory not found: {WEBSERVER_FILES_DIR}")

    if not os.path.exists(BACKEND_FILES_DIR):
        raise FileNotFoundError(f"Backend files directory not found: {BACKEND_FILES_DIR}")

    print("\nInstalling dependencies")
    install_dependencies()

    print("\n Setting up certificate for the backend")
    setup_backend_certificate()

    print("\nEnabling OVA upload to Proxmox")
    allow_ova_upload_to_proxmox()

    print("\nSetting up Proxmox API token")
    backend_api_token, web_server_api_token = setup_api_token()

    print("\nSetting up backend network")
    setup_backend_network(backend_api_token)

    print("\nGenerating and distributing environment files")
    generate_and_distribute_env_files(backend_api_token, web_server_api_token)

    print("\nSetting up backend DNSMasq")
    setup_backend_dnsmasq()

    print("\nSetting up OpenVPN server")
    setup_openvpn_server()

    print("\nSetting up web and database server")
    webserver_id, database_id = setup_web_and_database_server(backend_api_token)

    print("\nSetting up iptables")
    setup_iptables()

    print("\nSetting up database server")
    setup_database_server()

    print("\nSetting up webserver")
    setup_webserver()

    print("\nSetting up OpenVPN server")
    validate_running_and_reachable(webserver_id, database_id, backend_api_token)

    print("\nSetting up database")
    setup_database()

    print("\nStarting backend")
    start_backend()

    print("\tSetting up pool manager service")
    start_pool_manager()

    print("\nSetting up cleanup service")
    setup_cleanup_service()


def install_dependencies():
    """
    Install necessary dependencies.
    """
    global time_start

    subprocess.run(["timedatectl", "set-timezone", "Europe/Berlin"], check=True, capture_output=True)

    # Detect Debian version
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("DEBIAN_VERSION_FULL="):
                    debian_version = line.strip().split("=")[1].strip('"')
                    break
            else:
                debian_version = "0"  # fallback if not found
    except FileNotFoundError:
        debian_version = "0"

    print(f"\tDetected Debian version: {debian_version}")

    # Install appropriate ntpdate package
    if subprocess.run(["dpkg", "--compare-versions", debian_version, "ge", "13.0"]).returncode == 0:
        print("\tInstalling ntpsec-ntpdate (Debian >= 13)")
        subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "update"], check=True, capture_output=True)
        subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "install", "-y", "ntpsec-ntpdate"], check=True, capture_output=True)
    else:
        print("\tInstalling legacy ntpdate (Debian < 13)")
        subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "update"], check=True, capture_output=True)
        subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "install", "-y", "ntpdate"], check=True, capture_output=True)

    print("\tSynchronizing time with NTP server")
    subprocess.run(["ntpdate", "time.google.com"], check=True, capture_output=True)

    time_start = datetime.datetime.now()

    # Update and install required packages
    print("\tUpdating package list")
    subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "update"], check=True, capture_output=True)

    packages = [
        ("OpenVPN", ["openvpn"]),
        ("Easy-RSA", ["easy-rsa"]),
        ("dnsmasq", ["dnsmasq"]),
        ("iptables", ["iptables"]),
        ("sshpass", ["sshpass"]),
        ("postgres (used in testing)", ["postgresql", "postgresql-contrib"]),
        ("sudo (used in testing)", ["sudo"]),
        ("scapy (used in testing)", ["python3-scapy"]),
    ]

    for desc, pkgs in packages:
        print(f"\tInstalling {desc}")
        subprocess.run(["apt-get", "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}", "install", "-y"] + pkgs, check=True, capture_output=True)

    # Stop and disable PostgreSQL
    subprocess.run(["systemctl", "stop", "postgresql"], check=True, capture_output=True)
    subprocess.run(["systemctl", "disable", "postgresql"], check=True, capture_output=True)


def setup_backend_certificate():
    """
    Setup the backend certificate.
    """

    print("\tSetting up backend certificate directory")
    os.makedirs(BACKEND_CERTIFICATE_DIR, exist_ok=True)

    print("\tGenerating backend certificate and key")
    subprocess.run(["openssl", "req", "-x509", "-nodes", "-days", "3650",
                    "-newkey", "rsa:2048", "-keyout", BACKEND_CERTIFICATE_KEY_FILE,
                    "-out", BACKEND_CERTIFICATE_FILE, "-subj",
                    f"/CN={PROXMOX_HOST}/O=heiST Backend"], check=True, capture_output=True)


def allow_ova_upload_to_proxmox():
    """
    Allow OVA upload to Proxmox.
    """

    config_dir = "/etc/pve/storage.cfg"

    if not os.path.exists(config_dir):
        raise FileNotFoundError(f"Proxmox config directory not found: {config_dir}")

    with open(config_dir, "w") as config_file:
        config_file.write(f"""dir: local
        path /var/lib/vz
        content iso,vztmpl,backup,import

lvmthin: local-lvm
        thinpool data
        vgname pve
        content rootdir,images
""")


def setup_api_token():
    """
    Setup the Backend API token.
    """

    print("\tSetting up setup API token")

    proxmox = ProxmoxAPI("localhost", user=PROXMOX_USER, password=PROXMOX_PASSWORD, verify_ssl=False)

    user_id = f"{PROXMOX_USER}"
    token_id = f"backend-token"
    comment = "Backend API token"
    privsep = 0

    result = proxmox.access.users(user_id).token(token_id).post(
        comment=comment,
        privsep=privsep
    )

    backend_token = {"user": user_id, "token_name": token_id, "token_value": result["value"]}


    print("\tSetting up web server API token")

    user_id = f"{PROXMOX_USER}"
    token_id = f"webserver-token"
    comment = "Webserver API token"
    privsep = 1

    result = proxmox.access.users(user_id).token(token_id).post(
        comment=comment,
        privsep=privsep
    )

    role_id = "webserver-role"

    proxmox.access.roles.post(
        roleid=role_id,
        privs="Datastore.AllocateTemplate, Datastore.Allocate"
    )

    print("\tRestricting web server API token permissions")

    permissions = [
        {"path": f"/storage/local", "roles": role_id, "tokens": f"{user_id}!{token_id}"},
    ]

    for perm in permissions:
        proxmox.access.acl.put(
            path=perm["path"],
            roles=perm["roles"],
            tokens=perm["tokens"],
        )

    web_server_token = {"user": user_id, "token_name": token_id, "token_value": result["value"]}

    return backend_token, web_server_token


def setup_backend_network(api_token):
    """
    Setup the backend network.
    """

    print("\tSetting up backend network")
    proxmox = ProxmoxAPI("localhost", **api_token, verify_ssl=False)

    # Create the backend network
    proxmox.nodes(PROXMOX_HOSTNAME).network.create(
        iface=BACKEND_NETWORK_DEVICE,
        type='bridge',
        cidr=BACKEND_NETWORK_SUBNET,
        autostart=1,
    )

    proxmox.nodes(PROXMOX_HOSTNAME).network.put()

    print("\tWaiting for backend network to be created")
    while not os.path.exists(f"/sys/class/net/{BACKEND_NETWORK_DEVICE}"):
        pass


def generate_and_distribute_env_files(backend_api_token, web_server_api_token):
    """
    Generate and distribute the environment files.
    """

    backend_api_token_string = f"{backend_api_token['user']}!{backend_api_token['token_name']}={backend_api_token['token_value']}"
    web_server_api_token_string = f"{web_server_api_token['user']}!{web_server_api_token['token_name']}={web_server_api_token['token_value']}"

    # Generate the .env files for the database and webserver
    print("\tGenerating webserver .env file")
    with open(os.path.join(WEBSERVER_FILES_DIR, ".env"), "w") as web_env_file:
        web_env_file.write(f"PROXMOX_API_TOKEN='{web_server_api_token_string}'\n")
        web_env_file.write(f"PROXMOX_HOST='{PROXMOX_HOST}'\n")
        web_env_file.write(f"PROXMOX_PORT='{PROXMOX_PORT}'\n")
        web_env_file.write(f"PROXMOX_HOSTNAME='{PROXMOX_HOSTNAME}'\n")

        web_env_file.write(f"BACKEND_HOST='{PROXMOX_HOST}'\n")
        web_env_file.write(f"BACKEND_PORT='{BACKEND_PORT}'\n")
        web_env_file.write(f"BACKEND_AUTHENTICATION_TOKEN='{BACKEND_AUTHENTICATION_TOKEN}'\n")

        web_env_file.write(f"DB_HOST='{DATABASE_HOST}'\n")
        web_env_file.write(f"DB_NAME='{DATABASE_NAME}'\n")
        web_env_file.write(f"DB_USER='{WEBSERVER_DATABASE_USER}'\n")
        web_env_file.write(f"DB_PASSWORD='{WEBSERVER_DATABASE_PASSWORD}'\n")
        web_env_file.write(f"DB_PORT='{DATABASE_PORT}'\n")


    print("\tGenerating backend .env file")
    with open(os.path.join(BACKEND_FILES_DIR, ".env"), "w") as backend_env_file:
        backend_env_file.write(f"BACKEND_HOST='{PROXMOX_HOST}'\n")
        backend_env_file.write(f"BACKEND_PORT='{BACKEND_PORT}'\n")
        backend_env_file.write(f"BACKEND_LOGGING_DIR='{BACKEND_FILES_DIR}'\n")
        backend_env_file.write(f"BACKEND_CERTIFICATE_FILE='{BACKEND_CERTIFICATE_FILE}'\n")
        backend_env_file.write(f"BACKEND_CERTIFICATE_KEY_FILE='{BACKEND_CERTIFICATE_KEY_FILE}'\n")
        backend_env_file.write(f"BACKEND_AUTHENTICATION_TOKEN='{BACKEND_AUTHENTICATION_TOKEN}'\n")

        backend_env_file.write(f"DB_HOST='{DATABASE_HOST}'\n")
        backend_env_file.write(f"DB_NAME='{DATABASE_NAME}'\n")
        backend_env_file.write(f"DB_USER='{DATABASE_USER}'\n")
        backend_env_file.write(f"DB_PASSWORD='{DATABASE_PASSWORD}'\n")
        backend_env_file.write(f"DB_PORT='{DATABASE_PORT}'\n")

        backend_env_file.write(f"PROXMOX_URL='https://{PROXMOX_HOSTNAME}:{PROXMOX_PORT}'\n")
        backend_env_file.write(f"PROXMOX_API_TOKEN='{backend_api_token_string}'\n")
        backend_env_file.write(f"PROXMOX_HOSTNAME='{PROXMOX_HOSTNAME}'\n")

        backend_env_file.write(f"VPN_SERVER_IP='{PROXMOX_EXTERNAL_IP}'\n")

        backend_env_file.write(f"MONITORING_VPN_INTERFACE='{MONITORING_VPN_INTERFACE}'\n")
        backend_env_file.write(f"MONITORING_DMZ_INTERFACE='{MONITORING_DMZ_INTERFACE}'\n")
        backend_env_file.write(f"MONITORING_HOST='{MONITORING_HOST}'\n")
        backend_env_file.write(f"MONITORING_VM_ID={MONITORING_VM_ID}\n")
        backend_env_file.write(f"WAZUH_API_PORT='{WAZUH_PORT}'\n")
        backend_env_file.write(f"WAZUH_API_USER='{WAZUH_USER}'\n")
        backend_env_file.write(f"WAZUH_API_PASSWORD='{WAZUH_PASSWORD}'\n")
        backend_env_file.write(f"WAZUH_ENROLLMENT_PASSWORD='{WAZUH_ENROLLMENT_PASSWORD}'\n")
        backend_env_file.write(f"WAZUH_NETWORK_DEVICE='{WAZUH_NETWORK_DEVICE}'\n")

    print("\tGenerating testing .env file")
    with open(os.path.join(TESTING_FILES_DIR, ".env"), "w") as testing_env_file:
        testing_env_file.write(f"PROXMOX_USER='{PROXMOX_USER}'\n")
        testing_env_file.write(f"PROXMOX_PASSWORD='{PROXMOX_PASSWORD}'\n")
        testing_env_file.write(f"PROXMOX_HOST='{PROXMOX_HOST}'\n")
        testing_env_file.write(f"PROXMOX_PORT='{PROXMOX_PORT}'\n")
        testing_env_file.write(f"PROXMOX_HOSTNAME='{PROXMOX_HOSTNAME}'\n")
        testing_env_file.write(f"PROXMOX_URL='https://{PROXMOX_HOSTNAME}:{PROXMOX_PORT}'\n")
        testing_env_file.write(f"PROXMOX_API_TOKEN='{backend_api_token_string}'\n")

        testing_env_file.write(f"DB_HOST='{DATABASE_HOST}'\n")
        testing_env_file.write(f"DB_NAME='{DATABASE_NAME}'\n")
        testing_env_file.write(f"DB_USER='{DATABASE_USER}'\n")
        testing_env_file.write(f"DB_PASSWORD='{DATABASE_PASSWORD}'\n")
        testing_env_file.write(f"DB_PORT='{DATABASE_PORT}'\n")

        testing_env_file.write(f"BACKEND_HOST='{PROXMOX_HOST}'\n")
        testing_env_file.write(f"BACKEND_PORT='{BACKEND_PORT}'\n")
        testing_env_file.write(f"BACKEND_LOGGING_DIR='{BACKEND_FILES_DIR}'\n")
        testing_env_file.write(f"BACKEND_CERTIFICATE_FILE='{BACKEND_CERTIFICATE_FILE}'\n")
        testing_env_file.write(f"BACKEND_CERTIFICATE_KEY_FILE='{BACKEND_CERTIFICATE_KEY_FILE}'\n")
        testing_env_file.write(f"BACKEND_AUTHENTICATION_TOKEN='{BACKEND_AUTHENTICATION_TOKEN}'\n")

        testing_env_file.write(f"VPN_SERVER_IP='{PROXMOX_EXTERNAL_IP}'\n")


def setup_backend_dnsmasq():
    """
    Setup the dnsmasq service for the backend network.
    """

    print("\tDisabling and stopping existing dnsmasq service")
    subprocess.run(["systemctl", "disable", "dnsmasq"], check=True, capture_output=True)
    subprocess.run(["systemctl", "stop", "dnsmasq"], check=True, capture_output=True)

    print("\tGenerating dnsmasq configuration")
    dnsmasq_config = f"""interface={BACKEND_NETWORK_DEVICE}
bind-interfaces
except-interface=lo
dhcp-range={BACKEND_NETWORK_HOST_MIN},{BACKEND_NETWORK_HOST_MAX},12h
dhcp-option=option:router,{BACKEND_NETWORK_ROUTER}
dhcp-option=option:dns-server,{BACKEND_NETWORK_ROUTER},8.8.8.8,8.8.4.4

dhcp-host={DATABASE_MAC_ADDRESS},{DATABASE_HOST}
dhcp-host={WEBSERVER_MAC_ADDRESS},{WEBSERVER_HOST}
"""

    backend_dnsmasq_dir = "/etc/dnsmasq-backend"
    os.makedirs(backend_dnsmasq_dir, exist_ok=True)

    with open(os.path.join(backend_dnsmasq_dir, "dnsmasq.conf"), "w") as dnsmasq_file:
        dnsmasq_file.write(dnsmasq_config)

    print("\tSetting up dnsmasq service")
    with open(DNSMASQ_SERVICE_PATH, "w") as service_file:
        service_file.write(f"""[Unit]
Description=DNSMasq for Backend Network
After=network.target

[Service]
Type=forking
ExecStart=/usr/sbin/dnsmasq --conf-file={backend_dnsmasq_dir}/dnsmasq.conf --pid-file={backend_dnsmasq_dir}/dnsmasq.pid --dhcp-leasefile={backend_dnsmasq_dir}/dnsmasq.leases --log-facility={backend_dnsmasq_dir}/dnsmasq.log

[Install]
WantedBy=multi-user.target
""")

    print("\tEnabling and starting dnsmasq service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "dnsmasq-backend"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "dnsmasq-backend"], check=True, capture_output=True)


def setup_iptables():
    """
    Setup iptables rules for the backend network.
    """

    # Enable IP forwarding
    print("\tEnabling IP forwarding")
    with open("/etc/sysctl.d/99-sysctl.conf", "a") as sysctl_file:
        sysctl_file.write("\nnet.ipv4.ip_forward=1\n")
    subprocess.run(["sysctl", "--system"], check=True, capture_output=True)

    print("\tSetting up iptables rules")
    iptables_script_dir = "/etc/iptables-backend"
    os.makedirs(iptables_script_dir, exist_ok=True)
    iptables_script = f"""#!/bin/bash

# Flush existing rules
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X

# Set default policies
iptables -P INPUT ACCEPT
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Disallow traffic to the host from the VPN
iptables -A INPUT -i tun0 -j DROP

# Enable forwarding of internal connections
iptables -A FORWARD -i {BACKEND_NETWORK_DEVICE} -o {BACKEND_NETWORK_DEVICE} -j ACCEPT

# Allow established and related connections
iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT

# Port forwarding for HTTP (port 80)
iptables -t nat -A PREROUTING -p tcp -d {PROXMOX_INTERNAL_IP} --dport 80 -j DNAT --to-destination {WEBSERVER_HOST}:80

# Port forwarding for HTTPS (port 443)
iptables -t nat -A PREROUTING -p tcp -d {PROXMOX_INTERNAL_IP} --dport 443 -j DNAT --to-destination {WEBSERVER_HOST}:443

# Masquerade traffic from webserver back to outside world
iptables -t nat -A POSTROUTING -s {WEBSERVER_HOST} -o {BACKEND_NETWORK_DEVICE} -j MASQUERADE

# Allow forwarded HTTP traffic
iptables -A FORWARD -p tcp -d {WEBSERVER_HOST} --dport 80 -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -p tcp -s {WEBSERVER_HOST} --sport 80 -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow forwarded HTTPS traffic
iptables -A FORWARD -p tcp -d {WEBSERVER_HOST} --dport 443 -m state --state NEW,ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -p tcp -s {WEBSERVER_HOST} --sport 443 -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow internet access for the webserver and database server
iptables -t nat -A POSTROUTING -s {BACKEND_NETWORK_SUBNET} -o vmbr0 -j MASQUERADE
iptables -A FORWARD -i vmbr0 -o {BACKEND_NETWORK_DEVICE} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i {BACKEND_NETWORK_DEVICE} -o vmbr0 -j ACCEPT
"""

    with open(os.path.join(iptables_script_dir, "iptables.sh"), "w") as iptables_file:
        iptables_file.write(iptables_script)

    subprocess.run(["chmod", "+x", os.path.join(iptables_script_dir, "iptables.sh")], check=True, capture_output=True)

    print("\tSetting up iptables service")
    iptables_service = f"""[Unit]
Description=Iptables for Backend Network
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash {iptables_script_dir}/iptables.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
    with open(IPTABLES_SERVICE_PATH, "w") as service_file:
        service_file.write(iptables_service)

    print("\tEnabling and starting iptables service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "iptables-backend"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "iptables-backend"], check=True, capture_output=True)


def download_ubuntu_base_server_ova():
    """
    Download the Ubuntu Base Server OVA file.
    """

    scrip_dir = os.path.dirname(os.path.realpath(__file__))
    base_server_dir = os.path.join(scrip_dir, "ubuntu-base-server")
    base_server_file = os.path.join(base_server_dir, "ubuntu-base-server.ova")

    os.makedirs(base_server_dir, exist_ok=True)

    print("\tChecking if Ubuntu Base Server OVA file already exists")
    if not os.path.exists(base_server_file):
        print("\tDownloading Ubuntu Base Server OVA file")
        try:
            proc = subprocess.Popen(["wget", UBUNTU_BASE_SERVER_URL, "-O", base_server_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            if proc.returncode == 0:
                print("\tSuccessfully downloaded Ubuntu Base Server OVA file")
            else:
                print(f"\tFailed to download OVA: {stderr.decode()}")
        except subprocess.CalledProcessError as e:
            print(f"\tFailed to download OVA: {e.stderr.decode()}")
    else:
        print("\tUbuntu Base Server OVA file already exists. Skipping download.")

    return base_server_dir, base_server_file


def check_user_input(user_input):
    """
    Sanitize user input to prevent command injection attacks.
    """
    blacklist_pattern = r"""[;&|><`$\\'"*?{}\[\]~!#()=]+"""
    if re.search(blacklist_pattern, user_input):
        raise ValueError("Input contains potentially dangerous characters.")


def setup_web_and_database_server(api_token):
    """
    Setup the webserver VM.
    """

    webserver_id = 1000
    database_id = 2000

    # Download the Ubuntu Base Server OVA if it doesn't exist
    if os.path.exists("ubuntu-base-server") and not REUSE_DOWNLOADED_OVA:
        subprocess.run(["rm", "-rf", "ubuntu-base-server"], check=True, capture_output=True)

    base_server_dir, base_server_file = download_ubuntu_base_server_ova()

    print("\tExtracting OVA file")

    # Extract the OVA file
    subprocess.run(["tar", "-xf", base_server_file, "-C", base_server_dir],
                   check=True, capture_output=True)

    files = os.listdir(base_server_dir)
    ovf_file = next((f for f in files if f.endswith('.ovf')), None)
    check_user_input(ovf_file)

    if not ovf_file:
        raise FileNotFoundError("OVF file not found in the extracted OVA directory.")

    print("\tImporting OVA file as webserver")
    importovf_command = f"qm importovf {webserver_id} \"{base_server_dir}/{ovf_file}\" local-lvm"
    subprocess.run(importovf_command, shell=True, check=True, capture_output=True)

    print("\tImporting OVA file as database server")
    importovf_command = f"qm importovf {database_id} \"{base_server_dir}/{ovf_file}\" local-lvm"
    subprocess.run(importovf_command, shell=True, check=True, capture_output=True)

    proxmox = ProxmoxAPI("localhost", **api_token, verify_ssl=False)

    # Configure the webserver
    print("\tConfiguring webserver")
    proxmox.nodes(PROXMOX_HOSTNAME).qemu(webserver_id).config.put(
        name='WebServer',
        cpu='kvm64',
        cores=4,
        memory=1024 * 16,
        net0=f'virtio,bridge={BACKEND_NETWORK_DEVICE},macaddr={WEBSERVER_MAC_ADDRESS}',
        ipconfig0=f'ip={WEBSERVER_HOST}/24,gw={BACKEND_NETWORK_ROUTER}',
    )

    # Configure the database server
    print("\tConfiguring database server")
    proxmox.nodes(PROXMOX_HOSTNAME).qemu(database_id).config.put(
        name='DatabaseServer',
        cpu='kvm64',
        cores=4,
        memory=1024 * 32,
        net0=f'virtio,bridge={BACKEND_NETWORK_DEVICE},macaddr={DATABASE_MAC_ADDRESS}',
        ipconfig0=f'ip={DATABASE_HOST}/24,gw={BACKEND_NETWORK_ROUTER}',
    )

    # Start the webserver and database server
    print("\tSetting up systemd service to start webserver and database server")
    start_vm_service = f"""[Unit]
Description=Start Web and Database Server
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'qm start {webserver_id} & qm start {database_id} &'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

    with open("/etc/systemd/system/start-vm.service", "w") as service_file:
        service_file.write(start_vm_service)

    print("\tEnabling and starting systemd service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "start-vm"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "start-vm"], check=True, capture_output=True)

    # Wait for the webserver and database server to be up
    print("\tWaiting for webserver and database server to be up")
    while True:
        webserver_status = proxmox.nodes(PROXMOX_HOSTNAME).qemu(webserver_id).status.current.get()
        database_status = proxmox.nodes(PROXMOX_HOSTNAME).qemu(database_id).status.current.get()

        if webserver_status['status'] == 'running' and database_status['status'] == 'running':
            break

    print("\tWebserver and database server are up and running")

    return webserver_id, database_id


def setup_openvpn_server():
    """
    Setup the OpenVPN server.
    """

    netmask = OPENVPN_SUBNET.split("/")[1]
    netmask_string = "1" * int(netmask) + "0" * (32 - int(netmask))
    openvpn_netmask = ".".join([str(int(netmask_string[i:i + 8], 2)) for i in range(0, 32, 8)])

    print("\tSetting up OpenVPN server configuration")
    openvpn_config = f"""dev tun
proto udp
port 1194
ca /etc/openvpn/easy-rsa/pki/ca.crt
cert /etc/openvpn/easy-rsa/pki/issued/server.crt
key /etc/openvpn/easy-rsa/pki/private/server.key
dh /etc/openvpn/easy-rsa/pki/dh.pem
tls-auth /etc/openvpn/easy-rsa/ta.key 0

push "route {CHALLENGES_ROOT_SUBNET} {CHALLENGES_ROOT_SUBNET_MASK}"

server {OPENVPN_SUBNET.split("/")[0]} {openvpn_netmask}
topology subnet  # Allows full /32 client IP assignments

client-config-dir /etc/openvpn/ccd

script-security 2

keepalive 10 30
explicit-exit-notify 1

status /var/log/openvpn-status.log
verb 7
"""

    print("\tCreating working directory for OpenVPN setup")
    os.makedirs("openvpn_setup", exist_ok=True)
    workdir = os.path.abspath("openvpn_setup")

    # Setup Easy-RSA
    print("\tSetting up Easy-RSA")
    easyrsa_dir = os.path.join(workdir, "easy-rsa")
    os.makedirs(easyrsa_dir, exist_ok=True)

    try:
        for item in os.listdir("/usr/share/easy-rsa"):
            src = os.path.join("/usr/share/easy-rsa", item)
            dest = os.path.join(easyrsa_dir, item)
            if not os.path.exists(dest):
                os.symlink(src, dest)
    except Exception as e:
        raise Exception(f"Failed to set up Easy-RSA: {e}")

    env = os.environ.copy()
    env['EASYRSA_BATCH'] = '1'
    env['EASYRSA_REQ_CN'] = 'heiST CA'

    print("\tInitializing Easy-RSA PKI")
    easyrsa_binary = os.path.join(easyrsa_dir, "easyrsa")
    subprocess.run([easyrsa_binary, "init-pki"],
                   cwd=easyrsa_dir, check=True, capture_output=True, env=env)
    result = subprocess.run([easyrsa_binary, "build-ca", "nopass"],
                   cwd=easyrsa_dir, check=True, capture_output=True, env=env)
    subprocess.run([easyrsa_binary, "gen-req", "server", "nopass"],
                   cwd=easyrsa_dir, check=True, capture_output=True, env=env)
    subprocess.run([easyrsa_binary, "sign-req", "server", "server"],
                   cwd=easyrsa_dir, check=True, capture_output=True, env=env)
    subprocess.run([easyrsa_binary, "gen-dh"],
                   cwd=easyrsa_dir, check=True, capture_output=True, env=env)
    subprocess.run(["openvpn", "--genkey", "secret", os.path.join(easyrsa_dir, "ta.key")],
                   check=True, capture_output=True, env=env)

    print("\tCopying Easy-RSA files to OpenVPN directory")
    subprocess.run(["cp", "-r", easyrsa_dir, "/etc/openvpn/easy-rsa"], check=True, capture_output=True)

    print("\tCreating OpenVPN server configuration file")
    with open("/etc/openvpn/server.conf", "w") as openvpn_file:
        openvpn_file.write(openvpn_config)

    print("\tCreating directory for client configurations")
    os.makedirs("/etc/openvpn/ccd", exist_ok=True)

    print("\tCleaning up the working directory")
    subprocess.run(["rm", "-rf", workdir], check=True, capture_output=True)

    print("\tEnabling and starting OpenVPN service")
    subprocess.run(["systemctl", "enable", "openvpn@server"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "openvpn@server"], check=True, capture_output=True)

    print("\tRemoving working directory")
    subprocess.run(["rm", "-rf", workdir], check=True, capture_output=True)

def setup_database_server():
    """
    Setup the database server.
    """

    def execute_command(command, user="ubuntu", password="admin"):
        """
        Execute a command and return the output.
        """
        result = subprocess.run([
            "sshpass", "-p", password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{user}@{DATABASE_HOST}", command
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Command failed: {result.stderr}")

        return result.stdout

    print("\tWaiting for database server to be reachable through SSH")
    while True:
        try:
            execute_command("echo 'Database server is reachable'")
            break

        except Exception:
            pass

    print("\tStopping unattended-upgrades service on database server")
    try:
        execute_command("sudo systemctl stop unattended-upgrades")
        execute_command("sudo systemctl disable unattended-upgrades")
    except Exception as e:
        print(f"\tFailed to stop unattended-upgrades: {e}")

    # Synchronize the time with NTP server
    print("\tSynchronizing server time with NTP server")
    execute_command("sudo timedatectl set-timezone Europe/Berlin")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} update")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} install -y ntpdate")
    execute_command("sudo ntpdate time.google.com")

    # Install PostgreSQL on the database server
    print("\tInstalling PostgreSQL on the database server")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} update")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} install -y postgresql postgresql-contrib")
    execute_command("sudo systemctl enable postgresql")
    execute_command("sudo systemctl start postgresql")

    # Set up the database and user
    print("\tSetting up database and user")
    execute_command(f"""sudo -u postgres psql -c "CREATE DATABASE {DATABASE_NAME};" """)
    execute_command(f"""sudo -u postgres psql -c "ALTER USER {DATABASE_USER} WITH PASSWORD '{DATABASE_PASSWORD}';" """)

    # Set listen_addresses = '*'
    print("\tAllowing remote connections to PostgreSQL")
    execute_command(
        """sudo sed -i "s/^#listen_addresses =.*/listen_addresses = '*'/" $(find /etc/postgresql -name postgresql.conf)""")
    execute_command(
        """echo "host all all 0.0.0.0/0 md5" | sudo tee -a $(find /etc/postgresql -name pg_hba.conf) > /dev/null""")
    execute_command("sudo systemctl restart postgresql")

    # Add Proxmox SSH key to authorized_keys
    print("\tEnabling SSH public key authentication")
    proxmox_ssh_key = open("/root/.ssh/id_rsa.pub").read().strip()

    # root user
    execute_command("sudo mkdir -p /root/.ssh")
    execute_command("sudo touch /root/.ssh/authorized_keys")
    execute_command("sudo chmod 600 /root/.ssh/authorized_keys")
    execute_command("sudo chmod 700 /root/.ssh")
    execute_command(f"""echo "{proxmox_ssh_key}" | sudo tee -a /root/.ssh/authorized_keys > /dev/null""")

    # ubuntu user
    execute_command("sudo -u ubuntu mkdir -p /home/ubuntu/.ssh")
    execute_command("sudo -u ubuntu touch /home/ubuntu/.ssh/authorized_keys")
    execute_command("sudo -u ubuntu chmod 600 /home/ubuntu/.ssh/authorized_keys")
    execute_command("sudo -u ubuntu chmod 700 /home/ubuntu/.ssh")
    execute_command(
        f"""echo "{proxmox_ssh_key}" | sudo -u ubuntu tee -a /home/ubuntu/.ssh/authorized_keys > /dev/null""")

    # postgres user
    execute_command("sudo -u postgres mkdir -p /var/lib/postgresql/.ssh")
    execute_command("sudo -u postgres touch /var/lib/postgresql/.ssh/authorized_keys")
    execute_command("sudo -u postgres chmod 600 /var/lib/postgresql/.ssh/authorized_keys")
    execute_command("sudo -u postgres chmod 700 /var/lib/postgresql/.ssh")
    execute_command(
        f"""echo "{proxmox_ssh_key}" | sudo -u postgres tee -a /var/lib/postgresql/.ssh/authorized_keys > /dev/null""")

    # Disable password login for all users
    print("\tDisabling password login for all users")
    execute_command("sudo passwd -l root")
    execute_command("sudo passwd -l ubuntu")
    execute_command("sudo passwd -l postgres")
    execute_command("""sudo sed -i "s/^#PasswordAuthentication yes/PasswordAuthentication no/" /etc/ssh/sshd_config""")

    print("\tRestarting SSH service")
    subprocess.run([
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"root@{DATABASE_HOST}",
        "sudo systemctl restart ssh"
    ], check=True, capture_output=True)


def setup_webserver():
    """
    Setup the webserver.
    """

    def execute_command(command, user="ubuntu", password="admin"):
        """
        Execute a command and return the output.
        """
        result = subprocess.run([
            "sshpass", "-p", password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{user}@{WEBSERVER_HOST}", command
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Command failed: {result.stderr}")

        return result.stdout

    def copy_file_to_server(local_path, remote_path, user="ubuntu", password="admin"):
        """
        Copy a file to the server.
        """
        subprocess.run([
            "sshpass", "-p", password,
            "scp", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            local_path, f"{user}@{WEBSERVER_HOST}:{remote_path}"
        ], check=True, capture_output=True)

    def copy_directory_to_server(local_path, remote_path, user="ubuntu", password="admin"):
        """
        Copy a directory to the server.
        """
        subprocess.run([
            "sshpass", "-p", password,
            "scp", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-r", local_path, f"{user}@{WEBSERVER_HOST}:{remote_path}"
        ], check=True, capture_output=True)

    print("\tWaiting for webserver to be reachable through SSH")
    while True:
        try:
            execute_command("echo 'Webserver is reachable'")
            break

        except Exception:
            pass

    print("\tStopping unattended-upgrades service on webserver")
    try:
        execute_command("sudo systemctl stop unattended-upgrades")
        execute_command("sudo systemctl disable unattended-upgrades")
    except Exception as e:
        print(f"\tFailed to stop unattended-upgrades: {e}")

    os.makedirs(f"{WEBSERVER_FILES_DIR}/html/uploads", exist_ok=True)
    os.makedirs(f"{WEBSERVER_FILES_DIR}/html/uploads/avatars", exist_ok=True)

    # Synchronize the time with NTP server
    print("\tSynchronizing server time with NTP server")
    execute_command("sudo timedatectl set-timezone Europe/Berlin")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} update")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} install -y ntpdate")
    execute_command("sudo ntpdate time.google.com")

    # Install Apache, PHP, Redis and composer on the webserver
    print("\tInstalling Apache, PHP, and composer on the webserver")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} update")
    execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT} install -y apache2 php libapache2-mod-php php-curl php-pgsql php-xml php-mbstring php-xdebug php-sockets php-imagick composer redis-server php-redis")

    # Changing Redis Configuration
    print("\tChanging Redis Configuration")
    execute_command("sudo systemctl enable redis-server")
    execute_command("sudo cp /etc/redis/redis.conf /etc/redis/redis.conf.backup")
    execute_command(r"sudo sed -i -e 's/^bind 127\.0\.0\.1 -::1/#bind 127.0.0.1 -::1/' -e 's/^port 6379$/port 0/' -e 's|^# unixsocket /run/redis/redis-server.sock|unixsocket /run/redis/redis-server.sock|' -e 's/^# unixsocketperm 700/unixsocketperm 770/' /etc/redis/redis.conf")
    execute_command("sudo usermod -aG redis www-data")
    execute_command("sudo systemctl restart redis")

    # Enable Apache modules
    print("\tEnabling Apache modules")
    php_version = execute_command(r"php -v | grep -oP 'PHP \K[0-9]+\.[0-9]+'")
    php_version = "".join([c for c in php_version if c.isdigit() or c == "."])

    execute_command(f"sudo a2enmod php{php_version}")
    execute_command("sudo a2enmod rewrite")
    execute_command("sudo a2enmod include")

    # Copy the mpm_event.conf file
    print("\tCopying mpm_event.conf file")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, "mpm_event.conf"),
        "/tmp/mpm_event.conf"
    )

    # Copy the php.ini file
    print("\tCopying php.ini file")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, "php.ini"),
        f"/tmp/php.ini"
    )

    # Copy the 000-default.conf file
    print("\tCopying 000-default.conf file")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, "000-default.conf"),
        "/tmp/000-default.conf"
    )

    # Copy the .env file
    print("\tCopying .env file")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, ".env"),
        "/tmp/.env"
    )
    # Copy the rate_limit.php file
    print("\tCopying rate_limit.php file")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, "rate_limit.php"),
        "/tmp/rate_limit.php"
    )

    # Copy the webserver files
    print("\tCopying webserver files")
    copy_directory_to_server(
        f"{WEBSERVER_FILES_DIR}/html",
        "/tmp/html"
    )

    # Move the files to the correct locations
    print("\tMoving files to the correct locations")
    execute_command("sudo mv /tmp/mpm_event.conf /etc/apache2/mods-available/mpm_event.conf")
    execute_command(f"sudo mv /tmp/php.ini /etc/php/{php_version}/apache2/php.ini")
    execute_command("sudo mv /tmp/000-default.conf /etc/apache2/sites-available/000-default.conf")
    execute_command("sudo mv /tmp/rate_limit.php /var/www/rate_limit.php")
    execute_command("sudo mv /tmp/.env /var/www/.env")
    execute_command("sudo rm -rf /var/www/html")
    execute_command("sudo mv /tmp/html /var/www/html")

    execute_command("sudo chown -R www-data:www-data /var/www/html")

    print("\tSetting up vendor directory using composer")
    execute_command("sudo -u www-data composer update --working-dir=/var/www/html")
    execute_command("sudo -u www-data composer install --working-dir=/var/www/html")
    execute_command("sudo -u www-data composer dump-autoload --working-dir=/var/www/html")

    # Transfer ownership of the webserver files to the webserver user
    print("\tSetting ownership of webserver files")
    execute_command("sudo chown root:root /etc/apache2/mods-available/mpm_event.conf")
    execute_command("sudo chmod 644 /etc/apache2/mods-available/mpm_event.conf")

    execute_command(f"sudo chown root:root /etc/php/{php_version}/apache2/php.ini")
    execute_command("sudo chmod 644 /etc/apache2/apache2.conf")

    execute_command("sudo chown -R root:root /var/www/html/")
    execute_command("sudo chmod -R 755 /var/www/html/")

    execute_command("sudo chown -R www-data:www-data /var/www/html/vendor")
    execute_command("sudo chmod -R 755 /var/www/html/vendor")

    execute_command("sudo chown -R www-data:www-data /var/www/html/uploads")
    execute_command("sudo chmod -R 755 /var/www/html/uploads")

    execute_command("sudo chown root:root /var/www/rate_limit.php")
    execute_command("sudo chmod 644 /var/www/rate_limit.php")

    execute_command("sudo chown root:root /var/www/.env")
    execute_command("sudo chmod 644 /var/www/.env")

    execute_command("sudo chown root:root /var/www/html")

    print("\tCreating directories for the logs")
    execute_command("sudo mkdir -p /var/log/heiST")
    execute_command("sudo chown -R www-data:www-data /var/log/heiST")
    execute_command("sudo chmod 755 /var/log/heiST")

    print("\tCreating directories for the locks")
    execute_command("sudo mkdir -p /var/www/deployment_locks")
    execute_command("sudo chown -R www-data:www-data /var/www/deployment_locks")
    execute_command("sudo chmod -R 755 /var/www/deployment_locks")

    # Copy the backend certificate as trusted
    print("\tCopying backend certificate as trusted")
    copy_file_to_server(BACKEND_CERTIFICATE_FILE, "/tmp/backend.crt")
    execute_command("sudo cp /tmp/backend.crt /usr/local/share/ca-certificates/backend.crt")

    # Copy the proxmox certificate as trusted
    print("\tCopying Proxmox certificate as trusted")
    copy_file_to_server("/etc/pve/local/pve-ssl.pem", "/tmp/proxmox.crt")
    execute_command("sudo cp /tmp/proxmox.crt /usr/local/share/ca-certificates/proxmox.crt")
    execute_command(f"echo {PROXMOX_HOST} {PROXMOX_HOSTNAME} | sudo tee -a /etc/hosts > /dev/null")

    execute_command("sudo update-ca-certificates")

    # Generate a self-signed certificate for HTTPS
    print("\tGenerating self-signed SSL certificate")
    execute_command(
        'sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 '
        '-keyout /etc/ssl/private/apache-selfsigned.key '
        '-out /etc/ssl/certs/apache-selfsigned.crt '
        '-subj "/CN=localhost" '
        '-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"'
    )

    # Configure Apache for HTTPS
    print("\tEnabling SSL and default SSL site in Apache")
    execute_command("sudo a2enmod ssl")
    execute_command("sudo a2ensite default-ssl")

    # Replace default-ssl.conf with your custom version if needed
    print("\tCustomizing default-ssl.conf")
    copy_file_to_server(
        os.path.join(WEBSERVER_FILES_DIR, "default-ssl.conf"),
        "/tmp/default-ssl.conf"
    )
    execute_command("sudo mv /tmp/default-ssl.conf /etc/apache2/sites-available/default-ssl.conf")

    execute_command("sudo chown -R root:root /etc/apache2/sites-available")
    execute_command("sudo chmod -R 755 /etc/apache2/sites-available")

    print("\tHardening Apache headers to hide version and X-Powered-By")
    # 1) Set ServerTokens Prod and ServerSignature Off
    execute_command(
        "sudo sed -i 's/^ServerTokens.*/ServerTokens Prod/' /etc/apache2/conf-available/security.conf || echo 'ServerTokens Prod' | sudo tee -a /etc/apache2/conf-available/security.conf")
    execute_command(
        "sudo sed -i 's/^ServerSignature.*/ServerSignature Off/' /etc/apache2/conf-available/security.conf || echo 'ServerSignature Off' | sudo tee -a /etc/apache2/conf-available/security.conf")

    # 2) Disable PHP X-Powered-By for all installed PHP versions
    execute_command(
        "for f in /etc/php/*/apache2/php.ini; do sudo sed -i 's/^expose_php.*/expose_php = Off/' \"$f\" || echo 'expose_php = Off' | sudo tee -a \"$f\"; done")

    # 3) Enable mod_headers and unset extra headers
    execute_command("sudo a2enmod headers")
    execute_command("""
sudo tee /etc/apache2/conf-available/headers-hardening.conf <<'EOF'
<IfModule mod_headers.c>
   Header unset X-Powered-By
   Header unset X-AspNet-Version
   Header unset X-AspNetMvc-Version
</IfModule>
EOF
    """)
    execute_command("sudo a2enconf headers-hardening")

    # 4) Reload Apache to apply changes
    execute_command("sudo systemctl reload apache2")

    # Restart Apache
    print("\tRestarting Apache")
    execute_command("sudo systemctl restart apache2")

    # Install and configure the challenge worker cron job
    print("\tInstalling and configuring challenge worker cron job")
    execute_command("sudo touch /var/log/challenge_worker.log")
    execute_command("sudo chown www-data:www-data /var/log/challenge_worker.log")
    execute_command("sudo chmod 666 /var/log/challenge_worker.log")
    execute_command(
        f"""echo -e "*/1 * * * * www-data /usr/bin/php /var/www/html/backend/worker/worker.php >> /var/log/challenge_worker.log 2>&1\n" | sudo tee /etc/cron.d/challenge_worker > /dev/null""")
    execute_command("sudo chmod 644 /etc/cron.d/challenge_worker")
    execute_command("sudo chown root:root /etc/cron.d/challenge_worker")

    # Add Proxmox SSH key to authorized_keys
    print("\tEnabling SSH public key authentication")
    proxmox_ssh_key = open("/root/.ssh/id_rsa.pub").read().strip()

    # root user
    execute_command("sudo mkdir -p /root/.ssh")
    execute_command("sudo touch /root/.ssh/authorized_keys")
    execute_command("sudo chmod 600 /root/.ssh/authorized_keys")
    execute_command("sudo chmod 700 /root/.ssh")
    execute_command(f"""echo "{proxmox_ssh_key}" | sudo tee -a /root/.ssh/authorized_keys > /dev/null""")

    # ubuntu user
    execute_command("sudo -u ubuntu mkdir -p /home/ubuntu/.ssh")
    execute_command("sudo -u ubuntu touch /home/ubuntu/.ssh/authorized_keys")
    execute_command("sudo -u ubuntu chmod 600 /home/ubuntu/.ssh/authorized_keys")
    execute_command("sudo -u ubuntu chmod 700 /home/ubuntu/.ssh")
    execute_command(
        f"""echo "{proxmox_ssh_key}" | sudo -u ubuntu tee -a /home/ubuntu/.ssh/authorized_keys > /dev/null""")

    # Disable password login for all users
    print("\tDisabling password login for all users")
    execute_command("sudo passwd -l root")
    execute_command("sudo passwd -l ubuntu")
    execute_command("""sudo sed -i "s/^#PasswordAuthentication yes/PasswordAuthentication no/" /etc/ssh/sshd_config""")

    print("\tRestarting SSH service")
    subprocess.run([
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"root@{WEBSERVER_HOST}",
        "sudo systemctl restart ssh"
    ], check=True, capture_output=True)


def validate_running_and_reachable(webserver_id, database_id, api_token, timeout=120):
    """
    Validate that the webserver and database server are running and reachable.
    """
    proxmox = ProxmoxAPI("localhost", **api_token, verify_ssl=False)

    # Check if the webserver and database server are running
    print("\tChecking if webserver and database server are running")
    webserver_running = False
    database_running = False
    start_time = time.time()
    while time.time() - start_time < timeout:
        webserver_status = proxmox.nodes(PROXMOX_HOSTNAME).qemu(webserver_id).status.current.get()
        database_status = proxmox.nodes(PROXMOX_HOSTNAME).qemu(database_id).status.current.get()

        if webserver_status['status'] == 'running':
            webserver_running = True
        if database_status['status'] == 'running':
            database_running = True

        if webserver_running and database_running:
            break

    if not webserver_running:
        raise Exception("Webserver is not running.")

    if not database_running:
        raise Exception("Database server is not running.")

    # Check if the webserver and database server are reachable
    print("\tChecking if webserver and database server are reachable")
    webserver_reachable = False
    database_reachable = False
    start_time = time.time()
    while time.time() - start_time < timeout and not (webserver_reachable and database_reachable):
        if not webserver_reachable:
            try:
                response = requests.get(f"https://{WEBSERVER_HOST}:{WEBSERVER_HTTPS_PORT}", timeout=5, verify=False)
                if response.status_code == 200:
                    webserver_reachable = True

            except Exception:
                pass

        if not database_reachable:
            try:
                connection = psycopg2.connect(
                    dbname=DATABASE_NAME,
                    user=DATABASE_USER,
                    password=DATABASE_PASSWORD,
                    host=DATABASE_HOST,
                    port=DATABASE_PORT
                )
                database_reachable = True
                connection.close()

            except Exception:
                pass

    if not webserver_reachable:
        raise Exception("Webserver is not reachable.")

    if not database_reachable:
        raise Exception("Database server is not reachable.")


def generate_udf_migration(
    sql_dir: str,
    output_file: str,
    target_schema: str,
    owner_role: str,
    limited_user: str,
    limited_user_password: str,
    database_name: str,
):
    """
    Generate a migration SQL script that:
      - Moves functions from 'api' subdirectory to a dedicated schema.
      - Adds functions from 'public' subdirectory to public schema (no move).
      - Sets the owner and SECURITY DEFINER.
      - Creates and configures a restricted user with limited access.

    Args:
        sql_dir: Directory containing .sql files with function definitions.
        output_file: Path for the generated migration SQL file.
        target_schema: Schema to move the API functions into.
        owner_role: Database role that will own and define the functions.
        limited_user: Name of the restricted user to create.
        limited_user_password: Password for the restricted user.
        database_name: Target database for privilege revocation and grants.
    """
    func_pattern = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([\w\.]+)\s*\(([^)]*)\)",
        re.IGNORECASE
    )

    def parse_functions(sql_text):
        funcs = []
        for match in func_pattern.finditer(sql_text):
            fullname = match.group(1).strip()
            args = match.group(2).strip()
            args = re.sub(r"\s+", " ", args)
            funcs.append((fullname, args))
        return funcs

    api_funcs = []
    public_funcs = []

    api_dir = os.path.join(sql_dir, "api")
    if os.path.exists(api_dir):
        for root, _, files in os.walk(api_dir):
            for file in files:
                if file.endswith(".sql"):
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        sql = f.read()
                        funcs = parse_functions(sql)
                        if funcs:
                            api_funcs.extend(funcs)

    public_dir = os.path.join(sql_dir, "public")
    if os.path.exists(public_dir):
        for root, _, files in os.walk(public_dir):
            for file in files:
                if file.endswith(".sql"):
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        sql = f.read()
                        funcs = parse_functions(sql)
                        if funcs:
                            public_funcs.extend(funcs)

    with open(output_file, "w", encoding="utf-8") as out:
        out.write(f"-- Auto-generated migration script\n")
        out.write(f"-- Moves API functions to schema '{target_schema}', "
                  f"sets owner '{owner_role}', and configures restricted user '{limited_user}'\n")
        out.write(f"-- Public functions remain in public schema with postgres owner\n\n")

        # 1. Create target schema
        out.write(f"CREATE SCHEMA IF NOT EXISTS {target_schema} AUTHORIZATION {owner_role};\n\n")

        # 2. Alter API functions (move to target schema)
        if api_funcs:
            out.write(f"-- API Functions (moved to {target_schema} schema)\n")
            for fullname, args in api_funcs:
                func_name = fullname.split(".")[-1]
                out.write(f"ALTER FUNCTION public.{func_name}({args}) SET SCHEMA {target_schema};\n")
                out.write(f"ALTER FUNCTION {target_schema}.{func_name}({args}) OWNER TO {owner_role};\n")
                out.write(f"ALTER FUNCTION {target_schema}.{func_name}({args}) SECURITY DEFINER;\n\n")

        # 3. Set owner for public functions (stay in public schema)
        if public_funcs:
            out.write(f"-- Public Functions (remain in public schema with postgres owner)\n")
            for fullname, args in public_funcs:
                func_name = fullname.split(".")[-1]
                out.write(f"ALTER FUNCTION public.{func_name}({args}) OWNER TO postgres;\n")
                out.write(f"ALTER FUNCTION public.{func_name}({args}) SECURITY DEFINER;\n\n")

        # 4. Create restricted user and configure privileges
        out.write(f"-- Create restricted user if not exists\n")
        out.write(f"DO $$ BEGIN\n")
        out.write(f"   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{limited_user}') THEN\n")
        out.write(f"      CREATE USER {limited_user} WITH PASSWORD '{limited_user_password}' "
                  f"NOCREATEDB NOCREATEROLE NOINHERIT;\n")
        out.write(f"   END IF;\n")
        out.write(f"END $$;\n\n")

        out.write(f"-- Revoke public privileges\n")
        out.write(f"REVOKE ALL ON DATABASE {database_name} FROM PUBLIC;\n")
        out.write(f"REVOKE ALL ON SCHEMA public FROM PUBLIC;\n")
        out.write(f"REVOKE ALL ON SCHEMA {target_schema} FROM PUBLIC;\n\n")

        out.write(f"-- Grant restricted permissions\n")
        out.write(f"GRANT USAGE ON SCHEMA {target_schema} TO {limited_user};\n")
        out.write(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {target_schema} TO {limited_user};\n\n")
        out.write(f"GRANT CONNECT ON DATABASE {database_name} TO {limited_user};\n\n")
        out.write(f"ALTER ROLE {limited_user} SET search_path = {target_schema}, public;\n\n")

        out.write(f"-- Ensure future functions inherit EXECUTE for limited user\n")
        out.write(f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA {target_schema}\n")
        out.write(f"GRANT EXECUTE ON FUNCTIONS TO {limited_user};\n")


def setup_database(conn=None):
    """
    Setup the database.
    """

    connection_managed_externally = conn is not None

    if not conn:
        conn = psycopg2.connect(
            dbname=DATABASE_NAME,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT
        )

    if not connection_managed_externally:
        print("\tReading init.sql file")
    init_sql_path = os.path.join(DATABASE_FILES_DIR, "init.sql")
    if not os.path.exists(init_sql_path):
        raise FileNotFoundError(f"SQL file not found: {init_sql_path}")

    with open(init_sql_path, "r") as file:
        init_script = file.read()

    if not connection_managed_externally:
        print("\tExecuting init.sql script")
    with conn.cursor() as cursor:
        cursor.execute(init_script)

    for schema_dir in os.listdir(os.path.join(DATABASE_FILES_DIR, "functions")):
        for functions_file in os.listdir(os.path.join(DATABASE_FILES_DIR, "functions", schema_dir)):
            if functions_file.endswith(".sql"):
                if not connection_managed_externally:
                    print(f"\tExecuting functions/{functions_file} script")
                with open(os.path.join(DATABASE_FILES_DIR, "functions", schema_dir, functions_file), "r") as file:
                    functions_script = file.read()
                with conn.cursor() as cursor:
                    cursor.execute(functions_script)

    if not connection_managed_externally:
        print("\tGenerating and executing UDF migration script")
    database_functions_path = os.path.join(DATABASE_FILES_DIR, "functions")
    udf_migration_path = os.path.join(DATABASE_FILES_DIR, "migrate_functions.sql")
    generate_udf_migration(
        sql_dir=database_functions_path,
        output_file=udf_migration_path,
        target_schema="api",
        owner_role="postgres",
        limited_user=WEBSERVER_DATABASE_USER,
        limited_user_password=WEBSERVER_DATABASE_PASSWORD,
        database_name=DATABASE_NAME
    )
    with open(udf_migration_path, "r") as file:
        udf_migration_script = file.read()
    with conn.cursor() as cursor:
        cursor.execute(udf_migration_script)

    conn.commit()

    # Setup the website admin user
    if not connection_managed_externally:
        print("\tSetting up website admin user")
    with conn.cursor() as cursor:
        WEBSITE_ADMIN_PASSWORD_SALT = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        WEBSITE_ADMIN_PASSWORD_HASH = hashlib.sha512((WEBSITE_ADMIN_PASSWORD_SALT + WEBSITE_ADMIN_PASSWORD).encode()).hexdigest()

        cursor.execute(
            "INSERT INTO users (username, email, password_hash, password_salt, is_admin) VALUES (%s, %s, %s, %s, %s)",
            (WEBSITE_ADMIN_USER, "admin@localhost.local", WEBSITE_ADMIN_PASSWORD_HASH, WEBSITE_ADMIN_PASSWORD_SALT, True))

    conn.commit()

    # Setup the challenge subnets and VPN static IPs
    if not connection_managed_externally:
        print("\tGenerating challenge subnets")
    challenge_subnet_base = "10.128.0.0"
    challenge_subnets_sql = "INSERT INTO challenge_subnets (subnet, available) VALUES "
    for i in range(2 ** (32 - 9 - 8)):
        subnet = f"{nth_challenge_subnet(challenge_subnet_base, i)}"
        challenge_subnets_sql += f"('{subnet}', true)" + ("," if i < 2 ** (32 - 9 - 8) - 1 else ";")

    if not connection_managed_externally:
        print("\tGenerating VPN static IPs")
    vpn_server_subnet = OPENVPN_SUBNET[:-3]
    vpn_static_ips_sql = "INSERT INTO vpn_static_ips (vpn_static_ip) VALUES "
    for i in range(2, 2 ** (32 - 16) - 1):
        vpn_static_ip = f"{nth_vpn_static_ip(vpn_server_subnet, i)}"
        vpn_static_ips_sql += f"('{vpn_static_ip}')" + ("," if i < 2 ** (32 - 16) - 2 else ";")

    with conn.cursor() as cursor:
        if not connection_managed_externally:
            print("\tSetting up challenge subnets table")
        cursor.execute(challenge_subnets_sql)
        if not connection_managed_externally:
            print("\tSetting up VPN static IPs table")
        cursor.execute(vpn_static_ips_sql)

    conn.commit()

    # Give vpn ip to admin user
    if not connection_managed_externally:
        print("\tGiving VPN IP to admin user")
    vpn_static_ip = nth_vpn_static_ip(OPENVPN_SUBNET[:-3], 2)
    with conn.cursor() as cursor:
        cursor.execute(f"UPDATE users SET vpn_static_ip = %s WHERE username = %s RETURNING id",
                       (vpn_static_ip, WEBSITE_ADMIN_USER))
        admin_user_id = cursor.fetchone()[0]
        cursor.execute(f"UPDATE vpn_static_ips SET user_id = %s WHERE vpn_static_ip = %s",
                       (admin_user_id, vpn_static_ip))

    if not connection_managed_externally:
        conn.close()


def start_backend():
    """
    Start the backend service.
    """
    print("\tSetting up backend service")
    backend_service = f"""[Unit]
Description=Backend Service
After=network.target

[Service]
Type=simple
ExecStart={PROJECT_ROOT}/bin/api
Restart=always
RestartSec=5
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
"""

    with open(os.path.join(SYSTEMD_PATH, "backend.service"), "w") as service_file:
        service_file.write(backend_service)

    print("\tEnabling and starting backend service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "backend"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "backend"], check=True, capture_output=True)


def start_pool_manager():
    """
    Start the pool manager service.
    """

    pool_manager_service = f"""[Unit]
Description=Pool Manager Service
After=network.target

[Service]
Type=simple
WorkingDirectory={BACKEND_FILES_DIR}
ExecStart={PROJECT_ROOT}/bin/pool_manager
Restart=always
RestartSec=5
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
"""

    with open(os.path.join(SYSTEMD_PATH, "pool_manager.service"), "w") as service_file:
        service_file.write(pool_manager_service)

    print("\tEnabling and starting pool manager service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "pool_manager"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "pool_manager"], check=True, capture_output=True)


def setup_cleanup_service():
    """
    Setup the cleanup script.
    """

    print("\tWriting cleanup service")
    cleanup_service = f"""[Unit]
Description=Cleanup Service
After=network.target

[Service]
Type=oneshot
ExecStart={PROJECT_ROOT}/bin/cleanup
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

    with open(os.path.join(SYSTEMD_PATH, "cleanup.service"), "w") as service_file:
        service_file.write(cleanup_service)

    print("\tEnabling and starting cleanup service")
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "enable", "cleanup"], check=True, capture_output=True)


def setup_pool_size_prediction_cron_job():
    """
    Setup the pool size prediction cron job to run every day at 5:30 AM.
    """

    print("\tSetting up pool size prediction cron job")
    cron_job = f"30 5 * * * root /usr/bin/python3 {BACKEND_FILES_DIR}/pool_size_prediction.py >> /var/log/pool_size_prediction.log 2>&1\n"
    with open("/etc/cron.d/pool_size_prediction", "w") as cron_file:
        cron_file.write(cron_job)
    subprocess.run(["chmod", "644", "/etc/cron.d/pool_size_prediction"], check=True, capture_output=True)
    subprocess.run(["chown", "root:root", "/etc/cron.d/pool_size_prediction"], check=True, capture_output=True)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        if sys.argv[2] == "-h" or sys.argv[2] == "--help":
            print("Usage: python setup.py [--download-ova]")
            sys.exit(0)

        if len(sys.argv) != 3 or sys.argv[2] not in ["--download-ova"]:
            print("Invalid arguments. Use --download-ova to download the OVA file.")
            sys.exit(1)

        if sys.argv[2] == "--download-ova":
            REUSE_DOWNLOADED_OVA = False

    setup()
    time_end = datetime.datetime.now()

    time_elapsed = time_end - time_start
    hours, remainder = divmod(time_elapsed.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)

    print(f"Setup completed in {int(hours):02}:{int(minutes):02}:{int(seconds):02}")
    print("All services are running and reachable.")