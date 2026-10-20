loc() (
	set -o pipefail
	local logs location

	logs=$(docker logs gluetun 2>&1) || {
		printf '%s\n' "$logs" >&2
		return 1
	}

	location=$(printf '%s\n' "$logs" | grep -F 'Public IP address is' | tail -n 1)

	if [[ -z "$location" ]]; then
		printf '%s\n' 'no public ip/location entry found in gluetun logs' >&2
		return 1
	fi

	printf '%s\n' "${location#*Public IP address is }"
)
