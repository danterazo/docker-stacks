#!/usr/bin/env python3
"""Start the Radeon LXCs only after safe host GPU and cooling readiness."""

import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


NODE = 'kveikur'
GPUS = ('0000:30:00.0', '0000:43:00.0')
GUESTS = ((150, 'vllm'), (151, 'llama-cpp'))
PCI_ROOT = Path('/sys/bus/pci/devices')
HWMON_ROOT = Path('/sys/class/hwmon')
DRI_ROOT = Path('/dev/dri')
KFD = Path('/dev/kfd')
FAN_STATUS = Path('/run/amd-fan/status.json')
CAP_HELPER = Path('/usr/local/sbin/v620-powercap-host.py')
PCT = '/usr/sbin/pct'
PVESH = '/usr/bin/pvesh'
SYSTEMCTL = '/usr/bin/systemctl'
CAP_UW = 200_000_000
MINIMUM_UW = 120_000_000


class ReadinessError(RuntimeError):
	"""A required safety condition or guest configuration is not ready."""


def command(args: List[str], *, timeout: int = 30) -> str:
	try:
		result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=True)
	except subprocess.CalledProcessError as exc:
		raise ReadinessError(f'command failed: {args[0]} (exit {exc.returncode})') from exc
	except (OSError, subprocess.SubprocessError) as exc:
		raise ReadinessError(f'command failed: {args[0]} ({type(exc).__name__})') from exc
	return result.stdout


def device_path(*, link: Path, pattern: str, major: int) -> str:
	if not link.is_symlink():
		raise ReadinessError(f'missing PCI device link: {link}')
	try:
		path = link.resolve(strict=True)
		info = path.stat()
	except OSError as exc:
		raise ReadinessError(f'cannot resolve PCI device link: {link}') from exc
	if path.parent != DRI_ROOT or not re.fullmatch(pattern, path.name):
		raise ReadinessError(f'unexpected GPU device path: {path}')
	if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != major:
		raise ReadinessError(f'not an expected DRM character device: {path}')
	return str(path)


def gpu_devices() -> Dict[str, str]:
	try:
		kfd = KFD.stat()
	except OSError as exc:
		raise ReadinessError('KFD device is unavailable') from exc
	if not stat.S_ISCHR(kfd.st_mode):
		raise ReadinessError('KFD is not a character device')
	result = {'dev0': f'{KFD},gid=993,mode=0660'}
	paths = set()
	for index, pci in enumerate(GPUS):
		device = PCI_ROOT / pci
		try:
			identity = tuple((device / key).read_text().strip() for key in ('vendor', 'device', 'subsystem_vendor', 'subsystem_device'))
			driver = (device / 'driver').resolve(strict=True).name
		except OSError as exc:
			raise ReadinessError(f'GPU {pci} is unavailable') from exc
		if identity != ('0x1002', '0x73a1', '0x1002', '0x0e34') or driver != 'amdgpu':
			raise ReadinessError(f'GPU {pci} identity or driver is incorrect')
		card = device_path(link=DRI_ROOT / 'by-path' / f'pci-{pci}-card', pattern=r'card\d+', major=226)
		render = device_path(link=DRI_ROOT / 'by-path' / f'pci-{pci}-render', pattern=r'renderD\d+', major=226)
		paths.update((card, render))
		result[f'dev{1 + index * 2}'] = f'{card},gid=44,mode=0660'
		result[f'dev{2 + index * 2}'] = f'{render},gid=993,mode=0660'
	if len(paths) != 4:
		raise ReadinessError('GPU device paths are not distinct')
	return result


def check_fan_status(*, status_path: Path = FAN_STATUS, now: Optional[float] = None) -> None:
	try:
		status = json.loads(status_path.read_text())
		age = (time.monotonic() if now is None else now) - float(status['updated_monotonic'])
	except (OSError, ValueError, TypeError, KeyError) as exc:
		raise ReadinessError('host fan status is unavailable') from exc
	if (status.get('control_enabled') is not True or status.get('bmc_reachable') is not True
			or status.get('readback_degraded') or not 0 <= age <= 20):
		raise ReadinessError('host fan or BMC readback is not healthy and fresh')


def gpu_caps() -> Dict[str, int]:
	cards: Dict[str, int] = {}
	for hwmon in HWMON_ROOT.glob('hwmon*'):
		try:
			if (hwmon / 'name').read_text().strip() != 'amdgpu':
				continue
			pci = (hwmon / 'device').resolve(strict=True).name
			if pci not in GPUS:
				continue
			labels = {}
			for label_path in hwmon.glob('temp*_label'):
				label = label_path.read_text().strip()
				if label in ('edge', 'junction', 'mem'):
					if label in labels:
						raise ReadinessError(f'duplicate GPU temperature label: {pci}')
					labels[label] = int(label_path.with_name(label_path.name.replace('_label', '_input')).read_text())
			if set(labels) != {'edge', 'junction', 'mem'} or not all(0 <= value < 90_000 for value in labels.values()):
				raise ReadinessError(f'GPU temperatures missing or unsafe: {pci}')
			minimum = int((hwmon / 'power1_cap_min').read_text())
			maximum = int((hwmon / 'power1_cap_max').read_text())
			if not minimum <= MINIMUM_UW <= CAP_UW <= maximum:
				raise ReadinessError(f'GPU does not support 120–200 W: {pci}')
			if pci in cards:
				raise ReadinessError(f'duplicate GPU power interface: {pci}')
			current = int((hwmon / 'power1_cap').read_text())
			if not minimum <= current <= maximum:
				raise ReadinessError(f'GPU cap readback is outside its supported range: {pci}')
			cards[pci] = current
		except (OSError, ValueError) as exc:
			raise ReadinessError(f'cannot read GPU telemetry at {hwmon}') from exc
	if set(cards) != set(GPUS):
		raise ReadinessError('both expected V620 telemetry interfaces are required')
	return cards


def ready(*, timeout: float = 120) -> Dict[str, str]:
	deadline = time.monotonic() + timeout
	while True:
		try:
			command([SYSTEMCTL, 'is-active', '--quiet', 'amd-fan-host.service'])
			check_fan_status()
			devices = gpu_devices()
			gpu_caps()
			return devices
		except ReadinessError as exc:
			if time.monotonic() >= deadline:
				raise ReadinessError(f'host GPU startup preflight timed out: {exc}') from exc
			time.sleep(min(2, max(0, deadline - time.monotonic())))


def config(*, vmid: int, hostname: str, devices: Dict[str, str]) -> dict:
	try:
		value = json.loads(command([PVESH, 'get', f'/nodes/{NODE}/lxc/{vmid}/config', '--output-format', 'json']))
	except (ValueError, TypeError) as exc:
		raise ReadinessError(f'invalid CT {vmid} config response') from exc
	if value.get('hostname') != hostname or value.get('unprivileged') != 1 or value.get('onboot', 0) != 0:
		raise ReadinessError(f'CT {vmid} identity, privilege or boot policy changed')
	if value.get('lock'):
		raise ReadinessError(f'CT {vmid} is locked; leave its active task untouched')
	if not isinstance(value.get('digest'), str):
		raise ReadinessError(f'CT {vmid} config digest is missing')
	try:
		net = dict(part.split('=', 1) for part in value['net0'].split(','))
	except (KeyError, ValueError, AttributeError) as exc:
		raise ReadinessError(f'CT {vmid} network config is invalid') from exc
	expected_mac = f'DA:BE:EF:00:01:{vmid - 100:02d}'
	if (net.get('name') != 'eth0' or net.get('bridge') != 'vmbr0'
			or net.get('gw') != '192.168.10.1' or net.get('ip') != f'192.168.30.{vmid}/16'
			or net.get('hwaddr', '').upper() != expected_mac or net.get('rate', '0') != '0'):
		raise ReadinessError(f'CT {vmid} network identity or rate limit changed')
	device_keys = {key for key in value if re.fullmatch(r'dev\d+', key)}
	if device_keys != set(devices):
		raise ReadinessError(f'CT {vmid} has unexpected device entries')
	for key, wanted in devices.items():
		actual = value[key].split(',')
		expected = wanted.split(',')
		if len(actual) != 3 or sorted(actual[1:]) != sorted(expected[1:]):
			raise ReadinessError(f'CT {vmid} {key} permissions changed')
		if key == 'dev0' and actual[0] != '/dev/kfd':
			raise ReadinessError(f'CT {vmid} KFD path changed')
		if key != 'dev0':
			pattern = r'/dev/dri/card\d+' if key in ('dev1', 'dev3') else r'/dev/dri/renderD\d+'
			if not re.fullmatch(pattern, actual[0]):
				raise ReadinessError(f'CT {vmid} {key} path is unexpected')
	return value


def start_guests(*, devices: Dict[str, str]) -> None:
	states = {}
	configs = {}
	for vmid, hostname in GUESTS:
		configs[vmid] = config(vmid=vmid, hostname=hostname, devices=devices)
		state = command([PCT, 'status', str(vmid)]).strip()
		if state not in ('status: running', 'status: stopped'):
			raise ReadinessError(f'CT {vmid} has unexpected status: {state}')
		states[vmid] = state
		if state == 'status: running' and any(configs[vmid][key] != value for key, value in devices.items()):
			raise ReadinessError(f'CT {vmid} is running with stale GPU mappings')
	caps = gpu_caps()
	cold_start = all(state == 'status: stopped' for state in states.values())
	if cold_start and any(value != CAP_UW for value in caps.values()):
		command([sys.executable, str(CAP_HELPER), '--watts', '200'], timeout=60)
	if cold_start and any(value != CAP_UW for value in gpu_caps().values()):
		raise ReadinessError('200 W cap readback failed')
	check_fan_status()
	for vmid, _hostname in GUESTS:
		if states[vmid] == 'status: running':
			print(f'CT {vmid} already running with current GPU mappings')
			continue
		current = configs[vmid]
		if any(current[key] != value for key, value in devices.items()):
			args = [PCT, 'set', str(vmid), '--digest', current['digest']]
			for key, value in devices.items():
				args.extend((f'--{key}', value))
			command(args, timeout=60)
			updated = config(vmid=vmid, hostname=_hostname, devices=devices)
			if any(updated[key] != value for key, value in devices.items()):
				raise ReadinessError(f'CT {vmid} device update did not persist')
		check_fan_status()
		current_caps = gpu_caps()
		if cold_start and any(value != CAP_UW for value in current_caps.values()):
			raise ReadinessError('GPU cap changed before guest startup')
		command([PCT, 'start', str(vmid)], timeout=120)
		if command([PCT, 'status', str(vmid)]).strip() != 'status: running':
			raise ReadinessError(f'CT {vmid} did not start')
		print(f'CT {vmid} started with verified Radeon devices')


def main() -> int:
	if os.geteuid() != 0 or socket.gethostname().split('.')[0] != NODE:
		print('Radeon LXC startup must run as root on kveikur', file=sys.stderr)
		return 1
	try:
		start_guests(devices=ready())
	except ReadinessError as exc:
		print(f'Radeon LXC startup stopped: {exc}', file=sys.stderr)
		return 1
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
