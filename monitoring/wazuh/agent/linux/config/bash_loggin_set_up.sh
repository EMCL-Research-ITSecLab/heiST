#!/bin/bash
# This script sets up bash command logging permanently
# It's meant to be run by a systemd service after cloud-init

GLOBAL_BASHRC="/etc/bash.bashrc"
PROFILE_D_SCRIPT="/etc/profile.d/bash_logging.sh"
CONTAINER_NAME="${ENV_CONTAINER_NAME:-$(hostname)}"
PATH_BASH_CONF="/etc/rsyslog.d/bash.conf"
LOG_DESTINATION="local6.* /var/log/commands.log"
PRIVATE_LOG=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --private_log=*)
      PRIVATE_LOG="${1#*=}"
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
  shift
done

COMMAND_LOG_BASH="
# log last bash command to local6.debug which is located in /var/log/commands.log
export PROMPT_COMMAND='RETRN_VAL=\$?;logger -t bash_commands -p local6.debug \"Container $CONTAINER_NAME User \$(whoami) @ \$(pwd) Exit \${RETRN_VAL} [$$]: \$(history 1 | sed \"s/^[ ]*[0-9]\+[ ]*//\" )\"'
"

echo "[Info] Setting up bash command logging..."

# Create /var/log/commands.log if it doesn't exist
if [ ! -e "/var/log/commands.log" ]; then
  touch /var/log/commands.log
  echo "[Info] Created /var/log/commands.log"
fi
chmod 664 /var/log/commands.log

# 1. Add to /etc/profile.d/ (for login shells)
echo "[Info] Adding to $PROFILE_D_SCRIPT..."
echo "$COMMAND_LOG_BASH" > "$PROFILE_D_SCRIPT"
chmod 644 "$PROFILE_D_SCRIPT"

if [ -f "$PROFILE_D_SCRIPT" ]; then
  echo -e "\e[32m[Success]:\e[0m Created $PROFILE_D_SCRIPT"
else
  echo -e "\e[31m[ERROR]:\e[0m Failed to create $PROFILE_D_SCRIPT"
  exit 1
fi

# 2. Add to /etc/bash.bashrc (for interactive non-login shells)
echo "[Info] Adding to $GLOBAL_BASHRC..."

# Check if bashrc exists, if not create it
if [ ! -f "$GLOBAL_BASHRC" ]; then
  echo -e "\e[33m[Warning]:\e[0m $GLOBAL_BASHRC does not exist, creating it..."
  touch "$GLOBAL_BASHRC"
  chmod 644 "$GLOBAL_BASHRC"
fi

# Remove old entries if they exist (cleanup duplicates)
sed -i '/logger -t bash_commands -p local6.debug/d' "$GLOBAL_BASHRC" 2>/dev/null || true
sed -i '/# log last bash command to local6.debug/d' "$GLOBAL_BASHRC" 2>/dev/null || true

# Append the logging command
echo "$COMMAND_LOG_BASH" >> "$GLOBAL_BASHRC"

# Verify it was added
if grep -q "logger -t bash_commands -p local6.debug" "$GLOBAL_BASHRC"; then
  echo -e "\e[32m[Success]:\e[0m Added PROMPT_COMMAND to $GLOBAL_BASHRC"
else
  echo -e "\e[31m[ERROR]:\e[0m Failed to add PROMPT_COMMAND to $GLOBAL_BASHRC"
  exit 1
fi

# 3. Configure rsyslog
echo "[Info] Configuring rsyslog..."

# Create rsyslog config if it doesn't exist
if [ ! -f "$PATH_BASH_CONF" ]; then
  touch "$PATH_BASH_CONF"
fi

# Remove duplicates and add config
sed -i '/local6.*\/var\/log\/commands.log/d' "$PATH_BASH_CONF" 2>/dev/null || true
echo "$LOG_DESTINATION" >> "$PATH_BASH_CONF"

if [ -n "$PRIVATE_LOG" ]; then
  sed -i "\|local6.* $PRIVATE_LOG|d" "$PATH_BASH_CONF" 2>/dev/null || true
  echo "local6.* $PRIVATE_LOG" >> "$PATH_BASH_CONF"
fi

# 4. Set proper permissions on commands.log
chown syslog:syslog /var/log/commands.log 2>/dev/null || chown root:root /var/log/commands.log
chmod 644 /var/log/commands.log

# 5. Restart rsyslog
echo "[Info] Restarting rsyslog..."
systemctl restart rsyslog

if systemctl is-active --quiet rsyslog; then
  echo -e "\e[32m[Success]:\e[0m rsyslog restarted successfully"
else
  echo -e "\e[31m[ERROR]:\e[0m rsyslog failed to restart"
  exit 1
fi

echo -e "\e[32m[SUCCESS]:\e[0m Bash command logging setup complete!"
echo "[Info] Logging is now active in:"
echo "  - $PROFILE_D_SCRIPT (for login shells)"
echo "  - $GLOBAL_BASHRC (for interactive shells)"
echo "  - Logs written to: /var/log/commands.log"