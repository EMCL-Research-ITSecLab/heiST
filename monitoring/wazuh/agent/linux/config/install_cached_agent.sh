#!/bin/bash
# Install only a locally staged, checksum-verified package. Never downloads.
set -euo pipefail
case "${1:-}" in
    deb_amd|deb_aarch) extension=deb ;;
    rpm_amd|rpm_aarch|suse_amd|suse_aarch) extension=rpm ;;
    *) echo 'Unsupported cached agent OS type' >&2; exit 1 ;;
esac
cache_dir="${2:?Supply a package directory}"
package="$cache_dir/agent.$extension"
checksum="$package.sha256"
if [ ! -f "$package" ] || [ -L "$package" ] || [ ! -f "$checksum" ] || [ -L "$checksum" ]; then
    echo 'Cached agent package and checksum must be regular files' >&2; exit 1
fi
read -r expected < "$checksum"
if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo 'Expected a SHA256 digest on one line' >&2; exit 1
fi
actual="$(sha256sum -- "$package")"
if [ "${actual%% *}" != "$expected" ]; then
    echo 'Cached agent SHA256 mismatch' >&2; exit 1
fi
if [ "$extension" = deb ]; then
    dpkg --install "$package"
else
    rpm --install "$package"
fi
