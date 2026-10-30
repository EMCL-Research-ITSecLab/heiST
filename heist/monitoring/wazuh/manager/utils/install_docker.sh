#!/bin/bash

set -e  # Exit on any error

# Fresh cloud images may still be applying automatic security updates. Wait
# for the real dpkg lock instead of exhausting three short deployment retries.
APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-300}"
case "$APT_LOCK_TIMEOUT" in
    ''|*[!0-9]*) echo 'APT_LOCK_TIMEOUT must be a non-negative integer'; exit 1 ;;
esac
apt_get() {
    command apt-get -o "DPkg::Lock::Timeout=$APT_LOCK_TIMEOUT" "$@"
}

DIV="------------------------------------------------------"

if [ $(id -u) -ne 0 ]
then
    echo "Please run this script as root or using sudo!"
    exit 1
fi

function print_divider () {
    columns=80
    if [ -t 1 ]; then
        columns=$(tput cols 2>/dev/null || echo 80)
    fi
    printf "%${columns}s\n" | tr " " "-"
}

function section_header () {
    print_divider
    echo "${1}..."
    print_divider
}

function section_footer () {
    echo ""
}

function check_command_exists () {
    if ! command -v "$1" &> /dev/null; then
        echo "ERROR: Command $1 not found"
        return 1
    fi
    return 0
}

if [ $SUDO_USER ]
then
    user=$SUDO_USER
else
    user=`whoami`
fi

section_header "Add docker requirements and certificates"
apt_get update || { echo "ERROR: apt-get update failed"; exit 1; }
apt_get -y install ca-certificates curl sudo || { echo "ERROR: Failed to install prerequisites"; exit 1; }
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc || { echo "ERROR: Failed to download Docker GPG key"; exit 1; }
chmod a+r /etc/apt/keyrings/docker.asc
section_footer

section_header "Add docker apt repository"
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
apt_get update || { echo "ERROR: apt-get update failed after adding Docker repository"; exit 1; }
section_footer

section_header "Install docker packages"
apt_get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || { echo "ERROR: Failed to install Docker packages"; exit 1; }
section_footer

section_header "Add docker service and start it"
systemctl enable docker.service || { echo "ERROR: Failed to enable docker service"; exit 1; }
systemctl enable containerd.service || { echo "ERROR: Failed to enable containerd service"; exit 1; }
systemctl start docker || { echo "ERROR: Failed to start docker service"; exit 1; }
section_footer

section_header "Verify Docker is running"
sleep 5  # Give Docker time to fully start
if ! systemctl is-active --quiet docker; then
    echo "ERROR: Docker service is not running"
    systemctl status docker
    exit 1
fi
if ! check_command_exists docker; then
    exit 1
fi
docker --version || { echo "ERROR: Docker command failed"; exit 1; }
section_footer

section_header "Add docker group and add active user $user to docker group"
groupadd docker 2>/dev/null || true  # Don't fail if group already exists
usermod -aG docker $user || { echo "ERROR: Failed to add user to docker group"; exit 1; }
echo "Done. You might need to log out for group changes to take effect."
section_footer

section_header "Add docker-compose standalone binary"
curl -SL https://github.com/docker/compose/releases/download/v2.33.1/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose || { echo "ERROR: Failed to download docker-compose"; exit 1; }
chmod +x /usr/local/bin/docker-compose || { echo "ERROR: Failed to make docker-compose executable"; exit 1; }
section_footer

section_header "Final verification"
check_command_exists docker || exit 1
docker ps > /dev/null 2>&1 || { echo "ERROR: Docker is not functional"; exit 1; }
section_footer

echo "Docker installed successfully."
echo ""
exit 0
