#!/bin/sh
if (return 0 2>/dev/null); then
	printf 'Run this healthcheck with sh; do not source it\n' >&2
	return 1
fi
set -eu

service=${TS_SERVICE_NAME:?A Service name is required}
extra_port=${TS_SERVICE_EXTRA_PORT:?An additional listener port is required}

if wget -q -T 2 --spider http://127.0.0.1:9002/healthz &&
	address=$(
		if [ "${TS_USERSPACE:-true}" = true ]; then
			printf '127.0.0.1\n'
		else
			tailscale ip -4
		fi
	) && [ -n "$address" ] &&
	/bin/sh /etc/tailscale/check-service.sh "$address" &&
	nc -z -w 1 "$address" "$extra_port"; then
	timeout 4 tailscale serve advertise "$service" >/dev/null
else
	if ! timeout 4 tailscale serve drain "$service" >/dev/null 2>&1; then
		printf 'Unable to withdraw %s while its health check is failing\n' "$service" >&2
	fi
	exit 1
fi
