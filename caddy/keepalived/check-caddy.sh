#!/bin/sh
case "$0" in
*/check-caddy.sh | check-caddy.sh | */check-service.sh | check-service.sh) ;;
*)
	printf 'Run this healthcheck with sh; do not source it\n' >&2
	return 1
	;;
esac
set -eu

nc -z -w 1 127.0.0.1 80
nc -z -w 1 127.0.0.1 443
