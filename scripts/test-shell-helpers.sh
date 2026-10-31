#!/bin/bash

if (return 0 2>/dev/null); then
	return 1
fi

helpers_dir=${1:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../_common}
checks=0

for expansion in on off; do
	(
		if [[ $expansion == on ]]; then
			shopt -s expand_aliases
		else
			shopt -u expand_aliases
		fi
		alias_setting=$(shopt -p expand_aliases)
		source "$helpers_dir/functions.sh" || exit 1
		[[ $(type -t upgrade) == function ]] || exit 1
		[[ $(shopt -p expand_aliases) == "$alias_setting" ]] || exit 1

		record() {
			calls+=("$*")
			[[ $* != "$failure" ]]
		}
		sudo() { record "sudo $*"; }
		dpull() { record dpull; }
		bootstrap() { record bootstrap; }

		for helper in dbpull dupull dubpull durpull durbpull; do
			expected=()
			case "$helper" in
			dupull | dubpull | durpull | durbpull)
				expected+=("sudo apt-get update" "sudo apt-get dist-upgrade -y" "sudo apt-get clean" "sudo apt-get autoremove -y --purge")
				;;
			esac
			case "$helper" in
			dbpull | dubpull | durbpull) expected+=(bootstrap) ;;
			esac
			expected+=(dpull)
			case "$helper" in
			durpull | durbpull) expected+=("sudo reboot") ;;
			esac

			for failure in '' "${expected[@]}"; do
				calls=()
				expected_calls=()
				for step in "${expected[@]}"; do
					expected_calls+=("$step")
					[[ $step != "$failure" ]] || break
				done
				status=0
				"$helper" || status=$?
				if [[ "${calls[*]}" != "${expected_calls[*]}" ]] ||
					[[ -z $failure && $status != 0 ]] ||
					[[ -n $failure && $status == 0 ]]; then
					printf 'FAIL: %s, aliases %s, failure %s, status %s\n' "$helper" "$expansion" "${failure:-none}" "$status" >&2
					printf 'actual: %s\nexpected: %s\n' "${calls[*]}" "${expected_calls[*]}" >&2
					exit 1
				fi
				checks=$((checks + 1))
			done
		done
		printf 'PASS: %s mocked helper checks, aliases %s\n' "$checks" "$expansion"
	) || exit 1
done
