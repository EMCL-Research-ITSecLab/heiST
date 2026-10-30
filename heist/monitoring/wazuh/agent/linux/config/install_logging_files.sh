#!/bin/bash
# Copy staged logging files into their standard runtime locations and labels.
set -euo pipefail
config="${1:?Supply the staged agent configuration directory}"
install -D -m 0755 "$config/bash_loggin_set_up.sh" /usr/local/sbin/heist-bash-logging
install -D -m 0644 "$config/bash_loggin_systemd.service" /etc/systemd/system/bash_loggin_systemd.service
install -D -m 0644 "$config/bash_loggin_timer.timer" /etc/systemd/system/bash_loggin_timer.timer
# Moving files out of /var preserves var_t and prevents systemd reading units
# on enforcing SELinux guests. Restore the installed paths under normal policy.
if command -v restorecon >/dev/null 2>&1; then
    restorecon -F /usr/local/sbin/heist-bash-logging \
        /etc/systemd/system/bash_loggin_systemd.service \
        /etc/systemd/system/bash_loggin_timer.timer
elif command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = Enforcing ]; then
    echo 'SELinux is enforcing but restorecon is unavailable' >&2
    exit 1
fi
