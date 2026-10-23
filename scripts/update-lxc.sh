#!/bin/bash
## Update all LXCs
if (return 0 2>/dev/null); then
	printf 'Run this script with bash; do not source it\n' >&2
	return 1
fi
set -e

LXCS=(100 101)

for lxc in "${LXCS[@]}"; do
	ip="192.168.30.$lxc"
	echo "Updating LXC $lxc @ $ip..."

	ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$ip" "update"
done

echo -e "\nAll LXCs updated successfully!\n"
