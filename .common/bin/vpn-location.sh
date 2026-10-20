#!/usr/bin/env bash
# exit would close the caller's shell if this were sourced
(return 0 2>/dev/null) && {
	printf '%s\n' 'vpn-location.sh must be run, not sourced' >&2
	return 1
}
set -o pipefail

case "${1:-logs}" in
logs)
	logs=$(docker logs gluetun 2>&1) || {
		printf '%s\n' "$logs" >&2
		exit 1
	}

	location=$(printf '%s\n' "$logs" | grep -F 'Public IP address is' | tail -n 1)

	if [[ -z "$location" ]]; then
		printf '%s\n' 'no public ip/location entry found in gluetun logs' >&2
		exit 1
	fi

	printf '%s\n' "${location#*Public IP address is }"
	;;
live)
	docker run --rm \
		--network container:gluetun \
		--cap-drop ALL \
		--security-opt no-new-privileges:true \
		--read-only \
		curlimages/curl:latest \
		--fail --silent --show-error \
		--connect-timeout 5 --max-time 15 \
		https://ipinfo.io/json |
		jq --exit-status --raw-output '
			if all(.ip, .city, .country; type == "string" and length > 0) then
				"\(.ip) (\(.city), \(.country))"
			else
				error("public location response is missing IP, city, or country")
			end
		'
	;;
*)
	printf '%s\n' 'usage: vpn-location.sh [logs|live]' >&2
	exit 2
	;;
esac
