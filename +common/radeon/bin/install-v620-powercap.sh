#!/usr/bin/env bash
set -euo pipefail

repo_root=/docker
script_source="$repo_root/+common/radeon/bin/v620-powercap-apply.sh"
unit_source="$repo_root/+common/radeon/systemd/v620-powercap.service"
script_target=/usr/local/sbin/v620-powercap-apply.sh
unit_target=/etc/systemd/system/v620-powercap.service

if ((EUID != 0)); then
	echo "Run this installer as root." >&2
	exit 1
fi

if [[ "$(hostname)" != radeon-vm ]] || [[ "$(systemd-detect-virt --vm 2>/dev/null || true)" != kvm ]]; then
	echo "Refusing to install outside the radeon-vm KVM guest." >&2
	exit 1
fi

for source_path in "$script_source" "$unit_source"; do
	if [[ ! -f "$source_path" || -L "$source_path" ]]; then
		printf 'Required regular source file is missing or a symlink: %s\n' "$source_path" >&2
		exit 1
	fi
done

install_if_absent_or_same() {
	local source_path=$1
	local target_path=$2
	local mode=$3
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
echo "Installed but not enabled. Enable only after the patched amdgpu cap minimum is verified on attached V620 cards."
