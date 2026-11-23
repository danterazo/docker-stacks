#!/bin/sh
set -eu

: "${VLLM_API_KEY_NAMES:?VLLM_API_KEY_NAMES is required}"

set -- "$@" --api-key
for api_key_name in $VLLM_API_KEY_NAMES; do
	api_key=$(printenv "$api_key_name") || {
		printf '%s is required\n' "$api_key_name" >&2
		exit 1
	}
	if [ -z "$api_key" ]; then
		printf '%s is required\n' "$api_key_name" >&2
		exit 1
	fi
	set -- "$@" "$api_key"
done

exec vllm "$@"
