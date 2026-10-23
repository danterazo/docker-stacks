#!/bin/sh
case "$0" in
*/check-dns.sh | check-dns.sh | */check-service.sh | check-service.sh) ;;
*)
	printf 'Run this healthcheck with sh; do not source it\n' >&2
	return 1
	;;
esac
set -eu

address=${1:?A local DNS address is required}
timeout 3 nslookup -type=a id.samskeyti.net "$address" >/dev/null 2>&1
nc -z -w 1 "$address" 53 >/dev/null 2>&1
