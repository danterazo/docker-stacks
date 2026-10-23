#!/bin/sh
if (return 0 2>/dev/null); then
	printf 'Run this healthcheck with sh; do not source it\n' >&2
	return 1
fi
set -eu

nc -z -w 1 127.0.0.1 80
nc -z -w 1 127.0.0.1 443
