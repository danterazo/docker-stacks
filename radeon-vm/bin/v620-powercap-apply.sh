#!/usr/bin/env bash
if (return 0 2>/dev/null); then
	printf 'Run this script with Bash; do not source it\n' >&2
	return 1
fi
set -euo pipefail

if (($# == 0)); then
	set -- 180
fi

for attempt in {1..15}; do
	if bash /scripts/hardware/radeon-cap.sh >/dev/null 2>&1; then
		exec bash /scripts/hardware/radeon-cap.sh "$@"
	fi
	if ((attempt < 15)); then
		sleep 2
	fi
done

printf 'V620 power controls did not become ready; cap was not applied.\n' >&2
exit 1
