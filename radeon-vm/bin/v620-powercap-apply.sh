#!/usr/bin/env bash
set -euo pipefail

sysfs_root="${V620_SYSFS_ROOT:-/sys}"
watts="${1:-180}"

if [[ ! "$watts" =~ ^[0-9]+$ ]] || ((10#$watts < 120 || 10#$watts > 250)); then
	echo "Usage: $0 [120-250 watts]" >&2
	exit 2
fi

cap_uw=$((10#$watts * 1000000))
shopt -s nullglob

read_attribute() {
	local value
	[[ -r "$1" ]] || return 1
	value=$(<"$1") || return 1
	printf '%s' "$value"
}

is_v620() {
	local device_path=$1
	[[ "$(read_attribute "$device_path/vendor")" == 0x1002 ]] &&
		[[ "$(read_attribute "$device_path/device")" == 0x73a1 ]] &&
		[[ "$(read_attribute "$device_path/subsystem_vendor")" == 0x1002 ]] &&
		[[ "$(read_attribute "$device_path/subsystem_device")" == 0x0e34 ]]
}

find_hwmon() {
	local pci_path=$1
	local pci_real hwmon_path hwmon_real
	pci_real=$(readlink -f "$pci_path") || return 1
	for hwmon_path in "$sysfs_root"/class/hwmon/hwmon*; do
		[[ -e "$hwmon_path/device" ]] || continue
		hwmon_real=$(readlink -f "$hwmon_path/device") || continue
		[[ "$hwmon_real" == "$pci_real" ]] || continue
		[[ -r "$hwmon_path/power1_cap_min" && -r "$hwmon_path/power1_cap_max" && -w "$hwmon_path/power1_cap" ]] || continue
		printf '%s\n' "$hwmon_path"
		return 0
	done
	return 1
}

pci_devices=()
for device_path in "$sysfs_root"/bus/pci/devices/*; do
	if is_v620 "$device_path"; then
		pci_devices+=("$device_path")
	fi
done

if ((${#pci_devices[@]} == 0)); then
	echo "v620-powercap: no V620 detected; skipping"
	exit 0
fi

hwmon_paths=()
for attempt in {1..15}; do
	missing=()
	hwmon_paths=()
	for device_path in "${pci_devices[@]}"; do
		if hwmon_path=$(find_hwmon "$device_path"); then
			hwmon_paths+=("$hwmon_path")
		else
			missing+=("${device_path##*/}")
		fi
	done
	((${#missing[@]} == 0)) && break
	if ((attempt == 15)); then
		printf 'v620-powercap: no usable hwmon cap controls for V620 device(s): %s\n' "${missing[*]}" >&2
		exit 1
	fi
	sleep 2
done

failed=0
for index in "${!pci_devices[@]}"; do
	device_path=${pci_devices[$index]}
	hwmon_path=${hwmon_paths[$index]}
	minimum=$(read_attribute "$hwmon_path/power1_cap_min")
	maximum=$(read_attribute "$hwmon_path/power1_cap_max")
	cap_path="$hwmon_path/power1_cap"
	device_name=${device_path##*/}

	if [[ ! "$minimum" =~ ^[0-9]+$ || ! "$maximum" =~ ^[0-9]+$ ]] ||
		((cap_uw < minimum || cap_uw > maximum)); then
		printf 'v620-powercap: FAIL %s requested=%sW min=%s max=%s (uW)\n' "$device_name" "$watts" "$minimum" "$maximum" >&2
		failed=1
		continue
	fi

	previous=$(read_attribute "$cap_path")
	if [[ "$previous" != "$cap_uw" ]] && ! printf '%s\n' "$cap_uw" >"$cap_path"; then
		printf 'v620-powercap: FAIL %s write rejected\n' "$device_name" >&2
		failed=1
		continue
	fi

	actual=$(read_attribute "$cap_path")
	if [[ "$actual" != "$cap_uw" ]]; then
		printf 'v620-powercap: FAIL %s readback=%s expected=%s uW\n' "$device_name" "$actual" "$cap_uw" >&2
		failed=1
		continue
	fi
	printf 'v620-powercap: OK %s cap=%sW\n' "$device_name" "$watts"
done

if ((failed != 0)); then
	exit 1
fi

printf 'v620-powercap: applied %sW to %s V620 card(s)\n' "$watts" "${#pci_devices[@]}"
