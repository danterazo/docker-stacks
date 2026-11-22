#!/usr/bin/env bash
if (return 0 2>/dev/null); then
	printf 'Run this script with Bash; do not source it\n' >&2
	return 1
fi
set -euo pipefail

if ((EUID != 0)); then
	echo 'Run this installer as root.' >&2
	exit 1
fi
if [[ "$(hostname -s)" != kveikur || ! -d /etc/pve ]]; then
	echo 'Refusing to install outside the kveikur Proxmox host.' >&2
	exit 1
fi

repo_root="$(dirname -- "$(dirname -- "$(readlink -f -- "$0")")")"
script_source="$repo_root/bin/v620-powercap-host.py"
unit_source="$repo_root/systemd/v620-powercap-host.service"
script_target=/usr/local/sbin/v620-powercap-host.py
unit_target=/etc/systemd/system/v620-powercap-host.service

for source_path in "$script_source" "$unit_source"; do
	if [[ ! -f "$source_path" || -L "$source_path" ]]; then
		printf 'Required regular source file is missing or a symlink: %s\n' "$source_path" >&2
		exit 1
	fi
	done

install_if_absent_or_same() {
	local source_path=$1 target_path=$2 mode=$3
	if [[ -e "$target_path" || -L "$target_path" ]]; then
		if [[ -f "$target_path" && ! -L "$target_path" ]] && cmp -s "$source_path" "$target_path"; then
			printf 'Already current: %s\n' "$target_path"
			return
		fi
		printf 'Refusing to overwrite existing non-matching path: %s\n' "$target_path" >&2
		exit 1
	fi
	install -D -o root -g root -m "$mode" "$source_path" "$target_path"
	printf 'Installed: %s\n' "$target_path"
}

install_if_absent_or_same "$script_source" "$script_target" 0755
install_if_absent_or_same "$unit_source" "$unit_target" 0644
systemctl daemon-reload
echo 'Installed but not enabled. Enable only after host-owned V620s report the patched cap range and cooling is validated.'
