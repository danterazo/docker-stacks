#!/bin/bash
## Pull changes in all Git repos
if (return 0 2>/dev/null); then
	printf 'Run this script with bash; do not source it\n' >&2
	return 1
fi
set -e

LXCS=(100 101)

for lxc in "${LXCS[@]}"; do
	ip="192.168.30.$lxc"
	echo "Pulling on LXC $lxc @ $ip..."

	ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$ip" "cd /apps && git pull"
done

echo -e "\nAll repositories pulled successfully!\n"
