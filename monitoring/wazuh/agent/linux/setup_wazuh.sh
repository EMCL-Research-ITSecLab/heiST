#!/bin/bash
get_ipv6_by_mac_prefix() {
  local mac_prefix="${1,,}"
  local iface mac ipv6

  while IFS= read -r line; do
    iface=$(awk -F': ' '{print $2}' <<< "$line")
    mac=$(ip link show dev "$iface" 2>/dev/null | awk '/link\/ether/ {print $2}')
    if [[ -n "$mac" && "${mac,,}" == ${mac_prefix}* ]]; then
      ipv6=$(ip -6 addr show dev "$iface" 2>/dev/null \
             | awk '/inet6/ && $2 !~ /^fe80/ {print $2; exit}' \
             | cut -d'/' -f1 || true)
      if [[ -n "$ipv6" ]]; then
        printf '%s' "$ipv6"
        return 0
      fi
    fi
  done < <(ip -o link show)

  return 1
}

LOCAL_IP_ADDRESS=$(get_ipv6_by_mac_prefix "0a:01") || {
    print_info "[Warning] Could not detect a suitable IPv6 address for LOCAL_IP_ADDRESS, using dummy value. Only use this if you don't deploy wazuh immediately"
    LOCAL_IP_ADDRESS="::1"
}
MANAGER_IP_ADDRESS=$(hostname -I | awk '{print $1}')
AGENT_NAME="Agent_$LOCAL_IP_ADDRESS"
SYSTEM_HEALTH="true"
BASH_LOG="true"
UFW="true"
MODE="full"
ENROLLMENT_PASSWORD=""

OS_RPM_AMD="Linux RPM amd64"
OS_RPM_AARCH="Linux RPM aarch64"
OS_DEB_AMD="Linux DEB amd64"
OS_DEB_AARCH="Linux DEB aarch64"
OS_WIN="Windows MSI 32/64 bits"
OS_INTEL="macOS intel"
OS_SILICON="macOS Apple silicon"
OS_SUSE_AMD="SUSE Linux RPM amd64"
OS_SUSE_AARCH="SUSE Linux RPM aarch64"
OS_ARCH="Arch Linux"

CMD_RUN_LINUX=" systemctl daemon-reload &&  systemctl enable wazuh-agent &&  systemctl start wazuh-agent"
CMD_RUN_WIN="NET START WazuhSvc"
CMD_RUN_MAC=" /Library/Ossec/bin/wazuh-control start"
CMD_RUN_ARCH="$CMD_RUN_LINUX"

# Install commands WITHOUT env vars (clean install)
CMD_INSTALL_RPM_AMD='curl -o wazuh-agent-4.11.1-1.x86_64.rpm https://packages.wazuh.com/4.x/yum/wazuh-agent-4.11.1-1.x86_64.rpm && rpm -ihv wazuh-agent-4.11.1-1.x86_64.rpm'
CMD_INSTALL_RPM_AARCH='curl -o wazuh-agent-4.11.1-1.aarch64.rpm https://packages.wazuh.com/4.x/yum/wazuh-agent-4.11.1-1.aarch64.rpm && rpm -ihv wazuh-agent-4.11.1-1.aarch64.rpm'
CMD_INSTALL_DEB_AMD='wget https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/wazuh-agent_4.11.1-1_amd64.deb && dpkg -i ./wazuh-agent_4.11.1-1_amd64.deb'
CMD_INSTALL_DEB_AARCH='wget https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/wazuh-agent_4.11.1-1_arm64.deb && dpkg -i ./wazuh-agent_4.11.1-1_arm64.deb'
CMD_INSTALL_WIN='Invoke-WebRequest -Uri https://packages.wazuh.com/4.x/windows/wazuh-agent-4.11.1-1.msi -OutFile $env:tmp\\wazuh-agent; msiexec.exe /i $env:tmp\\wazuh-agent /q'
CMD_INSTALL_MAC_INTEL='curl -so wazuh-agent.pkg https://packages.wazuh.com/4.x/macos/wazuh-agent-4.11.1-1.intel64.pkg && installer -pkg ./wazuh-agent.pkg -target /'
CMD_INSTALL_MAC_SILICON='curl -so wazuh-agent.pkg https://packages.wazuh.com/4.x/macos/wazuh-agent-4.11.1-1.arm64.pkg && installer -pkg ./wazuh-agent.pkg -target /'

CMD_INSTALL_SUSE_AMD="$CMD_INSTALL_RPM_AMD"
CMD_INSTALL_SUSE_AARCH="$CMD_INSTALL_RPM_AARCH"

CMD_INSTALL_ARCH='
if command -v yay >/dev/null 2>&1; then
  yay -S --noconfirm wazuh-agent
elif command -v paru >/dev/null 2>&1; then
  paru -S --noconfirm wazuh-agent
else
   pacman -Syu --noconfirm wazuh-agent || { echo "[Error] wazuh-agent not in pacman repos. Install manually or use an AUR helper."; exit 1; }
fi
'

CMD_INSTALL="$CMD_INSTALL_DEB_AMD"

# Detect OS
detect_os() {
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH_SUFFIX="amd" ;;
        aarch64|arm64) ARCH_SUFFIX="aarch" ;;
        *) ARCH_SUFFIX="unknown" ;;
    esac

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            arch|manjaro) echo "arch" ;;
            opensuse*|sles|suse) echo "suse_${ARCH_SUFFIX}" ;;
            ubuntu|debian) echo "deb_${ARCH_SUFFIX}" ;;
            centos|rhel|fedora) echo "rpm_${ARCH_SUFFIX}" ;;
            *)
                if [ -f /etc/redhat-release ]; then
                    echo "rpm_${ARCH_SUFFIX}"
                elif [ -f /etc/debian_version ]; then
                    echo "deb_${ARCH_SUFFIX}"
                else
                    echo "unknown"
                fi
                ;;
        esac
    else
        echo "unknown"
    fi
}

function print_info() { echo -e "\e[34m[Info]:\e[0m $1" >> /root/wazuh_setup.log; }
function print_warning() { echo -e "\e[33m[Warning]:\e[0m $1" >> /root/wazuh_setup.log; }
function print_error() { echo -e "\e[31m[Error]:\e[0m $1" >> /root/wazuh_setup.log; }

update_ossec_config() {
    local config_file="/var/ossec/etc/ossec.conf"
    local new_manager="$1"

    if [ ! -f "$config_file" ]; then
        print_error "Config file $config_file not found!"
        return 1
    fi

    print_info "Updating manager address in ossec.conf..."

    # Update manager address
    if [ -n "$new_manager" ]; then
        sed -i "s|<address>.*</address>|<address>$new_manager</address>|g" "$config_file"
        print_info "Updated manager address to: $new_manager"
    fi
}

register_agent() {
    local manager_ip="$1"
    local agent_name="$2"
    local password="$3"
    local agent_auth_bin="/var/ossec/bin/agent-auth"

    if [ ! -x "$agent_auth_bin" ]; then
        print_error "agent-auth not found at $agent_auth_bin"
        return 1
    fi

    print_info "Registering agent with manager..."
    print_info "Executing: agent-auth -m $manager_ip -A $agent_name"

    # Direct call instead of eval - handles special characters correctly
    if [ -n "$password" ]; then
        "$agent_auth_bin" -m "$manager_ip" -A "$agent_name" -P "$password"
    else
        "$agent_auth_bin" -m "$manager_ip" -A "$agent_name"
    fi

    if [ $? -eq 0 ]; then
        print_info "Agent successfully registered!"
        return 0
    else
        print_error "Agent registration failed!"
        print_info "Troubleshooting:"
        print_info "  - Check if manager is reachable: ping $manager_ip"
        print_info "  - Verify port 1515 is open on manager"
        print_info "  - Check manager logs: /var/ossec/logs/ossec.log"
        return 1
    fi
}

reregister_agent() {
    local manager_ip="$1"
    local agent_name="$2"
    local password="$3"
    local client_keys="/var/ossec/etc/client.keys"

    print_warning "Re-registering agent (removing old keys)..."

    # Stop agent
    print_info "Stopping Wazuh agent..."
    systemctl stop wazuh-agent 2>/dev/null || /var/ossec/bin/wazuh-control stop 2>/dev/null || true

    # Backup and remove old keys
    if [ -f "$client_keys" ]; then
        cp "$client_keys" "${client_keys}.backup.$(date +%Y%m%d_%H%M%S)"
        rm -f "$client_keys"
        print_info "Old client.keys backed up and removed"
    fi

    # Register with new credentials
    register_agent "$manager_ip" "$agent_name" "$password"
}

OS_TYPE=$(detect_os)

# CLI arguments
SKIP_CONFIRMATION="false"
REREGISTER="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --manager=*) MANAGER_IP_ADDRESS="${1#*=}" ;;
    --name=*) AGENT_NAME="${1#*=}" ;;
    --password=*) ENROLLMENT_PASSWORD="${1#*=}" ;;
    --use_system_health=*) SYSTEM_HEALTH="${1#*=}" ;;
    --use_bash_log=*) BASH_LOG="${1#*=}" ;;
    --use_ufw=*) UFW="${1#*=}" ;;
    --os=*) OS_TYPE="${1#*=}" ;;
    --install) MODE="install" ;;
    --run) MODE="run" ;;
    --register) MODE="register" ;;
    --reregister) REREGISTER="true" ;;
    -y|--yes) SKIP_CONFIRMATION="true" ;;
    -h|--help)
        cat <<'EOF'
Usage: set_up_agent.sh [OPTIONS]

Options:
    --manager=<ip>              Manager IP address
    --name=<name>               Agent name
    --password=<pass>           Enrollment password (if required by manager)
    --use_system_health=<bool>  Enable system health logging (default: true)
    --use_bash_log=<bool>       Enable bash logging (default: true)
    --use_ufw=<bool>            Enable UFW logging (default: true)
    --os=<type>                 OS type (auto-detected by default)
    --install                   Only install the agent (don't configure/register)
    --register                  Only register agent (requires --manager and --name)
    --run                       Only start the agent
    --reregister                Remove old keys and re-register
    -y, --yes                   Skip confirmation prompts
    -h, --help                  Show this help

OS Types:
    rpm_amd, rpm_aarch, deb_amd, deb_aarch, suse_amd, suse_aarch,
    arch, win, mac_intel, mac_silicon

Modes:
    Default (no mode flag):  Full installation + registration + configuration + start
    --install:               Install agent only
    --register:              Register agent with manager (requires --manager and --name)
    --run:                   Start agent only
    --reregister:            Re-register agent (removes old keys first)

Examples:
    # Full installation with registration
    ./set_up_agent.sh --manager=192.168.1.100 --name=MyAgent

    # Install only (no registration)
    ./set_up_agent.sh --install -y

    # Register existing installation
    ./set_up_agent.sh --register --manager=192.168.1.200 --name=NewAgent -y

    # Re-register with new credentials
    ./set_up_agent.sh --reregister --manager=192.168.1.200 --name=NewAgentName -y

    # Register with enrollment password
    ./set_up_agent.sh --register --manager=192.168.1.100 --name=MyAgent --password=MySecretPass
EOF
        exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

# Validation for modes that require manager/name
if [ "$MODE" == "register" ] || [ "$REREGISTER" == "true" ]; then
    if [ -z "$MANAGER_IP_ADDRESS" ]; then
        print_error "Registration requires --manager=<ip>"
        exit 1
    fi
    if [ -z "$AGENT_NAME" ]; then
        print_error "Registration requires --name=<name>"
        exit 1
    fi
fi

# Map OS_TYPE to commands
case "$OS_TYPE" in
    rpm_amd) CMD_INSTALL="$CMD_INSTALL_RPM_AMD"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_RPM_AMD" ;;
    rpm_aarch) CMD_INSTALL="$CMD_INSTALL_RPM_AARCH"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_RPM_AARCH" ;;
    deb_amd) CMD_INSTALL="$CMD_INSTALL_DEB_AMD"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_DEB_AMD" ;;
    deb_aarch) CMD_INSTALL="$CMD_INSTALL_DEB_AARCH"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_DEB_AARCH" ;;
    suse_amd) CMD_INSTALL="$CMD_INSTALL_SUSE_AMD"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_SUSE_AMD" ;;
    suse_aarch) CMD_INSTALL="$CMD_INSTALL_SUSE_AARCH"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_SUSE_AARCH" ;;
    arch) CMD_INSTALL="$CMD_INSTALL_ARCH"; CMD_RUN="$CMD_RUN_ARCH"; OS="$OS_ARCH" ;;
    win) CMD_INSTALL="$CMD_INSTALL_WIN"; CMD_RUN="$CMD_RUN_WIN"; OS="$OS_WIN" ;;
    mac_intel) CMD_INSTALL="$CMD_INSTALL_MAC_INTEL"; CMD_RUN="$CMD_RUN_MAC"; OS="$OS_INTEL" ;;
    mac_silicon) CMD_INSTALL="$CMD_INSTALL_MAC_SILICON"; CMD_RUN="$CMD_RUN_MAC"; OS="$OS_SILICON" ;;
    *) CMD_INSTALL="$CMD_INSTALL_DEB_AMD"; CMD_RUN="$CMD_RUN_LINUX"; OS="$OS_DEB_AMD" ;;
esac

print_info "[Info] Mode: $MODE"
if [ "$REREGISTER" == "true" ]; then
    print_info "[Info] Reregister: enabled"
fi
print_info "[Info] Setting up Agent:"
print_info "OS: $OS"

if [ "$MODE" != "install" ] && [ "$MODE" != "run" ]; then
    print_info "Agent Name: $AGENT_NAME"
    print_info "Agent IP: $LOCAL_IP_ADDRESS"
    print_info "Manager IP: $MANAGER_IP_ADDRESS"

    if [ "$MANAGER_IP_ADDRESS" == "$LOCAL_IP_ADDRESS" ]; then
      print_warning "Wazuh manager has same address as wazuh agent. Provide --manager if that's unintended."
    fi
fi

if [ "$MODE" == "full" ] || [ "$MODE" == "install" ]; then
    print_info "Logging System Health: $SYSTEM_HEALTH"
    print_info "Logging Bash: $BASH_LOG"
    print_info "Logging UFW: $UFW"
fi

if [ "$SKIP_CONFIRMATION" != "true" ]; then
    print_info "Proceed with setup? [y/yes]"
    read -r CONFIRM
    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "yes" ]]; then
        print_info "Setup aborted"; exit 0
    fi
fi

# INSTALL MODE
if [ "$MODE" == "full" ] || [ "$MODE" == "install" ]; then
    print_info "Downloading and Installing Agent..."
    eval "$CMD_INSTALL"

    print_info "Adding Localfiles..."
    if [ -f /var/monitoring/wazuh-agent/config/localfile_ossec_config ]; then
       tee -a /var/ossec/etc/ossec.conf < /var/monitoring/wazuh-agent/config/localfile_ossec_config >/dev/null
    else
      print_warning "/var/monitoring/wazuh-agent/config/localfile_ossec_config not found — skipping append."
    fi

    if [ "$SYSTEM_HEALTH" == "true" ]; then
      if [ -f /var/monitoring/wazuh-agent/config/localfile_ossec_config_system_health ]; then
         tee -a /var/ossec/etc/ossec.conf < /var/monitoring/wazuh-agent/config/localfile_ossec_config_system_health >/dev/null
      else
        print_warning "/var/monitoring/wazuh-agent/config/localfile_ossec_config_system_health not found"
      fi
    fi

    if [ "$BASH_LOG" == "true" ]; then
      if [ -x /var/monitoring/wazuh-agent/config/bash_loggin_set_up.sh ]; then
        mkdir -p /etc/monitoring
        mv /var/monitoring/wazuh-agent/config/bash_loggin_set_up.sh /etc/monitoring
        chmod +x /etc/monitoring/bash_loggin_set_up.sh
        mv /var/monitoring/wazuh-agent/config/bash_loggin_systemd.service /etc/systemd/system/
        mv /var/monitoring/wazuh-agent/config/bash_loggin_timer.timer /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable bash_loggin_systemd.service
        systemctl enable bash_loggin_timer.timer
        systemctl start bash_loggin_systemd.service
        systemctl start bash_loggin_timer.timer
      else
        print_warning "/var/monitoring/wazuh-agent/config/bash_loggin_set_up.sh missing or not executable"
      fi
    fi

    if [ "$UFW" == "true" ]; then
        if [ -f /var/monitoring/wazuh-agent/config/localfile_ossec_config_ufw_status ]; then
           tee -a /var/ossec/etc/ossec.conf < /var/monitoring/wazuh-agent/config/localfile_ossec_config_ufw_status >/dev/null
        fi
    fi

    if [ "$BASH_LOG" == "false" ] && [ "$UFW" == "false" ] && [ "$SYSTEM_HEALTH" == "false" ]; then
        print_info "Nothing additional to set up."
    fi

    # Fix commands.log
    if [ -f /var/log/commands.log ]; then
        print_info "Setting up /var/log/commands.log..."
        chown syslog:syslog /var/log/commands.log
        chmod 644 /var/log/commands.log
        systemctl restart rsyslog || true
        print_info "/var/log/commands.log permissions updated and rsyslog restarted."
    fi
fi

# REGISTRATION
if [ "$MODE" == "full" ] || [ "$MODE" == "register" ] || [ "$REREGISTER" == "true" ]; then
    # Update manager address in config
    update_ossec_config "$MANAGER_IP_ADDRESS"

    # Register or re-register
    if [ "$REREGISTER" == "true" ]; then
        reregister_agent "$MANAGER_IP_ADDRESS" "$AGENT_NAME" "$ENROLLMENT_PASSWORD"
    else
        register_agent "$MANAGER_IP_ADDRESS" "$AGENT_NAME" "$ENROLLMENT_PASSWORD"
    fi

    if [ $? -ne 0 ]; then
        print_error "Registration failed. Please check the error messages above."
    fi

    if [ "$MODE" == "register" ]; then
        print_info "Agent registered. Use --run to start it."
    fi
fi

# START AGENT
if [ "$MODE" == "full" ] || [ "$MODE" == "register" ] || [ "$MODE" == "reregister" ]; then
    print_info "Starting Wazuh Agent..."
    eval "$CMD_RUN"
    print_info "Wazuh Agent is now running!"
fi

print_info "[Info] Wazuh Agent setup finished! (Mode: $MODE)"

touch /var/run/wazuh-setup-complete.flag
