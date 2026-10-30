#!/bin/bash

# ===========================
# Default Credentials
# ===========================
API_USER="wazuh-wui"
API_PASS="MyS3cr37P450r.*-"
DASH_USER="kibanaserver"
DASH_PASS="kibanaserver"
INDEXER_USER="admin"
INDEXER_PASS="SecretPassword"
ENROLLMENT_PASS="EnrollmentP@ss123"

# ===========================
# Parse CLI arguments
# ===========================
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-user)
      API_USER="$2"
      shift 2
      ;;
    --api-pass)
      API_PASS="$2"
      shift 2
      ;;
    --dashboard-user)
      DASH_USER="$2"
      shift 2
      ;;
    --dashboard-pass)
      DASH_PASS="$2"
      shift 2
      ;;
    --indexer-user)
      INDEXER_USER="$2"
      shift 2
      ;;
    --indexer-pass)
      INDEXER_PASS="$2"
      shift 2
      ;;
    --enrollment-pass)
      ENROLLMENT_PASS="$2"
      shift 2
      ;;
    *)
      echo "Unknown parameter: $1"
      exit 1
      ;;
  esac
done

# ===========================
# Functions
# ===========================
function print_info() {
    echo -e "\e[34m[Info]:\e[0m $1"
}

function print_warning() {
    echo -e "\e[33m[Warn]:\e[0m $1"
}

function print_error() {
    echo -e "\e[31m[Error]:\e[0m $1"
}

function escape_dollar_signs() {
    # Escape $ characters for docker-compose.yml by doubling them
    echo "$1" | sed 's/\$/\$\$/g'
}

# ===========================
# Prechecks
# ===========================
if [ $(id -u) -ne 0 ]; then
    echo "Please run this script as root or using sudo!"
    exit 1
fi

SYSCTL_CONF="/etc/sysctl.conf"
IP_ADDRESS=$(hostname -I | awk '{print $1}')
RAM_MIN=8388608
RAM=$(awk '/MemTotal/ {print $2}' /proc/meminfo)


if [ $RAM -le $RAM_MIN ]; then
    print_warning "Not Enough Memory! MINIMUM: $RAM_MIN, Current: $RAM"
    echo "Ignore warning? [y/yes]"
    read SET_UP_APPROVED
    if [ "$SET_UP_APPROVED" != "y" ] && [ "$SET_UP_APPROVED" != "yes" ]; then
        print_info "Setup Aborted"
        exit 1
    fi
fi

# ===========================
# Validate API Password Complexity
# ===========================
if ! echo "$API_PASS" | grep -Eq '^.{8,64}$' || \
   ! echo "$API_PASS" | grep -q '[a-z]' || \
   ! echo "$API_PASS" | grep -q '[A-Z]' || \
   ! echo "$API_PASS" | grep -q '[0-9]' || \
   ! echo "$API_PASS" | grep -Eq '[^A-Za-z0-9]'; then
  print_error "API password does not meet complexity requirements!"
  echo "Must be 8–64 chars with at least one uppercase, lowercase, number, and symbol."
  exit 1
fi

# ===========================
# Clone Repo
# ===========================
print_info "Cloning Wazuh Docker repository..."
if [ ! -d "wazuh-docker" ]; then
    git clone "https://github.com/wazuh/wazuh-docker.git" || {
        print_error "Failed to clone repository"
        exit 1
    }
else
    print_warning "Repository already exists, skipping clone."
fi

cd wazuh-docker
git checkout v4.11.1

# ===========================
# System Config
# ===========================
print_info "Setting vm.max_map_count..."
sysctl -w vm.max_map_count=262144
if grep -q "vm.max_map_count" "$SYSCTL_CONF"; then
    sed -i 's/^vm.max_map_count.*/vm.max_map_count=262144/' "$SYSCTL_CONF"
else
    echo "vm.max_map_count=262144" >> "$SYSCTL_CONF"
fi

# ===========================
# Generate Certificates
# ===========================
print_info "Generating certificates..."
cd single-node
sudo -u $SUDO_USER docker-compose -f generate-indexer-certs.yml run --rm generator

# ===========================
# Generate Hashes for Passwords
# ===========================
print_info "Generating hashed passwords for Indexer and Dashboard..."

# Generate password hashes using the -p flag
INDEXER_HASH=$(docker run --rm -i wazuh/wazuh-indexer:4.11.1 \
  bash /usr/share/wazuh-indexer/plugins/opensearch-security/tools/hash.sh -p "$INDEXER_PASS" | tail -n1)

DASHBOARD_HASH=$(docker run --rm -i wazuh/wazuh-indexer:4.11.1 \
  bash /usr/share/wazuh-indexer/plugins/opensearch-security/tools/hash.sh -p "$DASH_PASS" | tail -n1)

if [ -z "$INDEXER_HASH" ] || [ -z "$DASHBOARD_HASH" ]; then
  print_error "Password hashing failed! Check Docker and permissions."
  exit 1
fi

print_info "Indexer hash: $INDEXER_HASH"
print_info "Dashboard hash: $DASHBOARD_HASH"
print_info "Password hashes generated successfully."

# ===========================
# Update internal_users.yml
# ===========================
SECURITY_FILE="./config/wazuh_indexer/internal_users.yml"

print_info "Updating internal_users.yml for $INDEXER_USER and $DASH_USER..."

# Backup existing internal_users.yml
if [ -f "$SECURITY_FILE" ]; then
  cp "$SECURITY_FILE" "${SECURITY_FILE}.bak"
  print_info "Backup created: ${SECURITY_FILE}.bak"
else
  print_error "File $SECURITY_FILE not found!"
  exit 1
fi

# Escape special characters for sed
INDEXER_HASH_ESCAPED=$(echo "$INDEXER_HASH" | sed 's/[\/&$]/\\&/g')
DASHBOARD_HASH_ESCAPED=$(echo "$DASHBOARD_HASH" | sed 's/[\/&$]/\\&/g')

# Update hashes using sed with a different approach
sed -i "/^${INDEXER_USER}:/,/^[a-z]/ s|hash: \".*\"|hash: \"$INDEXER_HASH_ESCAPED\"|" "$SECURITY_FILE"
sed -i "/^${DASH_USER}:/,/^[a-z]/ s|hash: \".*\"|hash: \"$DASHBOARD_HASH_ESCAPED\"|" "$SECURITY_FILE"

print_info "Password hashes updated in internal_users.yml."

# Verify the hashes were updated
print_info "Verifying password hash updates..."
CURRENT_INDEXER_HASH=$(grep -A 2 "^${INDEXER_USER}:" "$SECURITY_FILE" | grep "hash:" | sed 's/.*hash: "\(.*\)".*/\1/')
CURRENT_DASHBOARD_HASH=$(grep -A 2 "^${DASH_USER}:" "$SECURITY_FILE" | grep "hash:" | sed 's/.*hash: "\(.*\)".*/\1/')

if [ "$CURRENT_INDEXER_HASH" = "$INDEXER_HASH" ]; then
    print_info "✓ Indexer user hash verified"
else
    print_error "✗ Indexer user hash NOT updated correctly!"
    print_error "Expected: $INDEXER_HASH"
    print_error "Got: $CURRENT_INDEXER_HASH"
    exit 1
fi

if [ "$CURRENT_DASHBOARD_HASH" = "$DASHBOARD_HASH" ]; then
    print_info "✓ Dashboard user hash verified"
else
    print_error "✗ Dashboard user hash NOT updated correctly!"
    print_error "Expected: $DASHBOARD_HASH"
    print_error "Got: $CURRENT_DASHBOARD_HASH"
    exit 1
fi

# ===========================
# Update Wazuh API user credentials in wazuh.yml
# ===========================
print_info "Updating Wazuh API credentials in wazuh.yml..."

WAZUH_YML_FILE="./config/wazuh_dashboard/wazuh.yml"

# Backup wazuh.yml if it exists
if [ -f "$WAZUH_YML_FILE" ]; then
  cp "$WAZUH_YML_FILE" "${WAZUH_YML_FILE}.bak"
  print_info "Backup created: ${WAZUH_YML_FILE}.bak"

  # Update username and password in wazuh.yml
  sed -i "s|\(username:\s*\).*|\1${API_USER}|" "$WAZUH_YML_FILE"
  sed -i "s|\(password:\s*\).*|\1\"${API_PASS}\"|" "$WAZUH_YML_FILE"
  print_info "Updated $WAZUH_YML_FILE with new API credentials."
else
  print_warning "File $WAZUH_YML_FILE not found; skipping API update."
fi

# ===========================
# Update wazuh_manager.conf with enrollment password configuration
# ===========================
WAZUH_MANAGER_CONF="./config/wazuh_cluster/wazuh_manager.conf"

print_info "Configuring enrollment password in wazuh_manager.conf..."

if [ -f "$WAZUH_MANAGER_CONF" ]; then
  # Backup wazuh_manager.conf
  cp "$WAZUH_MANAGER_CONF" "${WAZUH_MANAGER_CONF}.bak"
  print_info "Backup created: ${WAZUH_MANAGER_CONF}.bak"

  # Check if use_password exists and update it, or add it if it doesn't exist
  if grep -q "<use_password>" "$WAZUH_MANAGER_CONF"; then
    # use_password exists, update it
    sed -i "s|<use_password>.*</use_password>|<use_password>yes</use_password>|g" "$WAZUH_MANAGER_CONF"
    print_info "Updated existing use_password setting to 'yes'"
  else
    # use_password does not exist, add it to auth section
    if grep -q "<auth>" "$WAZUH_MANAGER_CONF"; then
      sed -i "/<auth>/a\    <use_password>yes</use_password>" "$WAZUH_MANAGER_CONF"
      print_info "Added use_password setting to auth section"
    else
      print_warning "No <auth> section found in wazuh_manager.conf, password authentication may not work"
    fi
  fi
else
  print_error "File $WAZUH_MANAGER_CONF not found!"
  exit 1
fi

# ===========================
# Update docker-compose.yml with CLI credentials
# ===========================
COMPOSE_FILE="docker-compose.yml"
print_info "Updating docker-compose.yml with provided credentials..."

# Backup docker-compose.yml
cp "$COMPOSE_FILE" "${COMPOSE_FILE}.bak"
print_info "Backup created: ${COMPOSE_FILE}.bak"

# Escape $ characters in passwords for docker-compose.yml
API_PASS_ESCAPED=$(escape_dollar_signs "$API_PASS")
DASH_PASS_ESCAPED=$(escape_dollar_signs "$DASH_PASS")
INDEXER_PASS_ESCAPED=$(escape_dollar_signs "$INDEXER_PASS")

# API credentials
sed -i "s#API_USERNAME=.*#API_USERNAME=${API_USER}#" "$COMPOSE_FILE"
sed -i "s#API_PASSWORD=.*#API_PASSWORD=${API_PASS_ESCAPED}#" "$COMPOSE_FILE"

# Dashboard credentials
sed -i "s#DASHBOARD_USERNAME=.*#DASHBOARD_USERNAME=${DASH_USER}#" "$COMPOSE_FILE"
sed -i "s#DASHBOARD_PASSWORD=.*#DASHBOARD_PASSWORD=${DASH_PASS_ESCAPED}#" "$COMPOSE_FILE"

# Indexer credentials
sed -i "s#INDEXER_USERNAME=.*#INDEXER_USERNAME=${INDEXER_USER}#" "$COMPOSE_FILE"
sed -i "s#INDEXER_PASSWORD=.*#INDEXER_PASSWORD=${INDEXER_PASS_ESCAPED}#" "$COMPOSE_FILE"

print_info "docker-compose.yml updated successfully."

# ===========================
# Start Docker Compose
# ===========================
print_info "Starting Docker Compose..."
sudo -u $SUDO_USER docker-compose up -d

# ===========================
# Wait for Wazuh Indexer to Initialize
# ===========================
print_info "Waiting for Wazuh Indexer to initialize (this may take 1-5 minutes)..."
sleep 90  # Initial wait

# Check if indexer is ready
INDEXER_CONTAINER=$(docker ps --filter "name=wazuh.indexer" --format "{{.Names}}" | head -n 1)
if [ -z "$INDEXER_CONTAINER" ]; then
    print_error "Wazuh Indexer container not found!"
    exit 1
fi

# Wait until indexer responds
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if docker exec "$INDEXER_CONTAINER" curl -s -k -u "${INDEXER_USER}:${INDEXER_PASS}" https://localhost:9200 > /dev/null 2>&1; then
        print_info "Wazuh Indexer is ready!"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        print_error "Wazuh Indexer did not start in time. Please check logs."
        exit 1
    fi
    echo -n "."
    sleep 10
done
echo ""

# ===========================
# Restart Containers to Apply Configuration Changes
# ===========================
print_info "Restarting containers to apply configuration changes..."
cd ..
sudo -u $SUDO_USER docker-compose -f single-node/docker-compose.yml down
sudo -u $SUDO_USER docker-compose -f single-node/docker-compose.yml up -d

# Wait for indexer to come back up
print_info "Waiting for Wazuh Indexer to restart (this may take 1-5 minutes)..."
sleep 90

# Check if indexer is ready
INDEXER_CONTAINER=$(docker ps --filter "name=wazuh.indexer" --format "{{.Names}}" | head -n 1)
if [ -z "$INDEXER_CONTAINER" ]; then
    print_error "Wazuh Indexer container not found after restart!"
    exit 1
fi

# Wait until indexer responds (using OLD credentials initially)
MAX_ATTEMPTS=30
ATTEMPT=0
print_info "Waiting for indexer to be ready..."
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if docker exec "$INDEXER_CONTAINER" curl -s -k https://localhost:9200 > /dev/null 2>&1; then
        print_info "Wazuh Indexer is ready!"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        print_error "Wazuh Indexer did not start in time. Please check logs."
        exit 1
    fi
    echo -n "."
    sleep 10
done
echo ""

# ===========================
# Apply Security Configuration with NEW Passwords
# ===========================
print_info "Applying OpenSearch security changes with new password hashes..."
docker exec -i "$INDEXER_CONTAINER" bash -c '
  export INSTALLATION_DIR=/usr/share/wazuh-indexer
  CACERT=$INSTALLATION_DIR/certs/root-ca.pem
  KEY=$INSTALLATION_DIR/certs/admin-key.pem
  CERT=$INSTALLATION_DIR/certs/admin.pem
  export JAVA_HOME=/usr/share/wazuh-indexer/jdk
  bash /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
    -cd /usr/share/wazuh-indexer/opensearch-security/ -nhnv \
    -cacert $CACERT -cert $CERT -key $KEY -p 9200 -icl
'

if [ $? -eq 0 ]; then
    print_info "Security configuration applied successfully with new passwords!"
else
    print_error "Failed to apply security configuration!"
    exit 1
fi

# Wait a moment for changes to propagate
print_info "Waiting for password changes to propagate..."
sleep 10

# ===========================
# Configure Enrollment Password in Container
# ===========================
print_info "Configuring agent enrollment password in container..."
MANAGER_CONTAINER=$(docker ps -aqf "name=single-node-wazuh.manager-1")

if [ -z "$MANAGER_CONTAINER" ]; then
    print_error "Wazuh Manager container not found!"
    exit 1
fi

# Create authd configuration with enrollment password
docker exec "$MANAGER_CONTAINER" bash -c "cat > /var/ossec/etc/authd.pass << EOF
$ENROLLMENT_PASS
EOF"

# Set proper permissions
docker exec "$MANAGER_CONTAINER" chown root:wazuh /var/ossec/etc/authd.pass
docker exec "$MANAGER_CONTAINER" chmod 640 /var/ossec/etc/authd.pass

print_info "Enrollment password file created successfully."

# ===========================
# Add Custom Rules (if they exist)
# ===========================
if [ -f "/var/lib/wazuh/manager/config/local_rules.xml" ]; then
    print_info "Adding custom rules..."
    docker cp /var/lib/wazuh/manager/config/local_rules.xml "${MANAGER_CONTAINER}:/var/ossec/etc/rules/local_rules.xml"
else
    print_warning "local_rules.xml not found at /var/lib/wazuh/manager/config/, skipping."
fi

if [ -f "/var/lib/wazuh/manager/config/local_decoder.xml" ]; then
    print_info "Adding custom decoders..."
    docker cp /var/lib/wazuh/manager/config/local_decoder.xml "${MANAGER_CONTAINER}:/var/ossec/etc/decoders/local_decoder.xml"
else
    print_warning "local_decoder.xml not found at /var/lib/wazuh/manager/config/, skipping."
fi

# ===========================
# Restart Manager to apply enrollment password and custom rules
# ===========================
print_info "Restarting Wazuh manager to apply changes..."
docker restart "$MANAGER_CONTAINER"
sleep 30

# ===========================
# Verify enrollment configuration
# ===========================
print_info "Verifying enrollment configuration..."
docker exec "$MANAGER_CONTAINER" bash -c '
if [ -f /var/ossec/etc/authd.pass ]; then
    echo "✓ Enrollment password file exists"
else
    echo "✗ Enrollment password file not found!"
    exit 1
fi

if grep -q "<use_password>yes</use_password>" /var/ossec/etc/ossec.conf; then
    echo "✓ Password authentication enabled in ossec.conf"
else
    echo "✗ Password authentication not properly configured!"
    exit 1
fi
'

if [ $? -eq 0 ]; then
    print_info "Enrollment configuration verified successfully!"
else
    print_error "Enrollment configuration verification failed!"
    exit 1
fi

# ===========================
# Finish
# ===========================
echo ""
echo "============================================"
print_info "Wazuh Docker Installation Finished!"
echo "============================================"
echo ""
echo "Dashboard URL:      https://$IP_ADDRESS"
echo ""
echo "Dashboard Login:"
echo "  User:             $DASH_USER"
echo "  Password:         $DASH_PASS"
echo ""
echo "Indexer Credentials:"
echo "  User:             $INDEXER_USER"
echo "  Password:         $INDEXER_PASS"
echo ""
echo "API Credentials:"
echo "  User:             $API_USER"
echo "  Password:         $API_PASS"
echo ""
echo "Agent Enrollment:"
echo "  Password:         $ENROLLMENT_PASS"
echo "  Server Address:   $IP_ADDRESS"
echo ""
echo "============================================"
echo ""
print_warning "Please change these passwords in production!"
echo ""
echo "To enroll agents, use:"
echo "  WAZUH_MANAGER='$IP_ADDRESS' WAZUH_REGISTRATION_PASSWORD='$ENROLLMENT_PASS' \\"
echo "  WAZUH_AGENT_NAME='agent-name' /var/ossec/bin/agent-auth"
echo ""