# sourced into the interactive shell by autoenv: no exit or set -e here

# last public ip/location reported in gluetun's logs
loc() (
	set -o pipefail
	logs=$(docker logs gluetun 2>&1) || {
		printf '%s\n' "$logs" >&2
		return 1
	}
	location=$(printf '%s\n' "$logs" | grep -F 'Public IP address is' | tail -n 1)
	if [[ -z $location ]]; then
		printf '%s\n' 'no public ip/location entry found in gluetun logs' >&2
		return 1
	fi
	printf '%s\n' "${location#*Public IP address is }"
)

# live public ip/location queried through gluetun's network
loc2() (
	set -o pipefail
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
)
