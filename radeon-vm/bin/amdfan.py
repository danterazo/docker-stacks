#!/usr/bin/env python3
"""Prototype GPU fan profile selection and monitoring; never writes to the BMC."""

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# provisional points for simulation only, not validated under GPU load
PROFILES: Dict[str, List[Tuple[int, int]]] = {
	'quiet': [(0, 10), (40, 10), (50, 20), (60, 35), (70, 60), (80, 100)],
	'balanced': [(0, 20), (40, 20), (50, 35), (60, 55), (70, 80), (80, 100)],
	'performance': [(0, 40), (40, 40), (50, 55), (60, 75), (70, 100)],
}
EXPECTED_GPUS = 2
REQUIRED_LABELS = ('edge', 'junction', 'mem')
GPU_VENDOR = '0x1002'
GPU_DEVICE = '0x73a1'
INTERVAL_SECONDS = 5
MAX_COOLDOWN_STEP_C = 3
DEFAULT_PROFILE = 'balanced'
LOG = logging.getLogger('amdfan')


class SensorError(Exception):
	"""An expected GPU or temperature reading is unavailable."""


def profile_path() -> Path:
	state = os.environ.get('XDG_STATE_HOME')
	return Path(state) / 'amdfan' / 'profile' if state else Path.home() / '.local/state/amdfan/profile'


def read_profile(*, path: Path) -> str:
	try:
		name = path.read_text(encoding='utf-8').strip()
	except FileNotFoundError:
		return DEFAULT_PROFILE
	if name not in PROFILES:
		raise ValueError('invalid saved profile')
	return name


def select_profile(*, path: Path, name: str) -> None:
	if name not in PROFILES:
		raise ValueError('invalid profile')
	path.parent.mkdir(parents=True, exist_ok=True)
	# replace an existing state file atomically without following its final symlink
	temp = path.with_name(f'.profile-{os.getpid()}')
	try:
		with temp.open('x', encoding='utf-8') as stream:
			stream.write(name + '\n')
		os.replace(temp, path)
	finally:
		if temp.exists():
			temp.unlink()


def read_gpus(*, root: Path) -> List[dict]:
	devices: Dict[str, dict] = {}
	try:
		entries = sorted(root.glob('hwmon*'))
		for path in entries:
			try:
				if (path / 'name').read_text(encoding='utf-8').strip() != 'amdgpu':
					continue
				device = path / 'device'
				if (device / 'vendor').read_text().strip() != GPU_VENDOR or (device / 'device').read_text().strip() != GPU_DEVICE:
					continue
				pci_id = device.resolve(strict=True).name
				if pci_id in devices:
					raise SensorError('duplicate GPU hwmon device')
				temps: Dict[str, float] = {}
				for label_path in sorted(path.glob('temp*_label')):
					label = label_path.read_text(encoding='utf-8').strip()
					if label not in REQUIRED_LABELS:
						continue
					if label in temps:
						raise SensorError(f'duplicate {label} temperature for {pci_id}')
					value_path = label_path.with_name(label_path.name.replace('_label', '_input'))
					value = int(value_path.read_text(encoding='utf-8').strip()) / 1000
					if not 0 <= value <= 125:
						raise SensorError(f'implausible {label} temperature for {pci_id}')
					temps[label] = value
				if set(temps) != set(REQUIRED_LABELS):
					raise SensorError(f'missing temperature for {pci_id}')
				devices[pci_id] = {'pci': pci_id, 'temperatures_c': temps}
			except (OSError, ValueError) as exc:
				raise SensorError(f'cannot read GPU sensor {path.name}: {exc}') from exc
	except OSError as exc:
		raise SensorError(f'cannot enumerate hwmon: {exc}') from exc
	if len(devices) != EXPECTED_GPUS:
		raise SensorError(f'expected {EXPECTED_GPUS} V620 GPUs, found {len(devices)}')
	return [devices[key] for key in sorted(devices)]


def duty_for(*, profile: str, temperature_c: float) -> int:
	points = PROFILES[profile]
	if temperature_c <= points[0][0]:
		return points[0][1]
	for (left_t, left_d), (right_t, right_d) in zip(points, points[1:]):
		if temperature_c <= right_t:
			return round(left_d + (right_d - left_d) * (temperature_c - left_t) / (right_t - left_t))
	return 100


def draft_bmc_curve(*, duty: int) -> dict:
	"""Describe the tested Zone3 request without sending it to the BMC."""
	if type(duty) is not int or not 0 <= duty <= 100:
		raise ValueError('duty must be an integer from 0 to 100')
	return {
		'PWMIndex': 2,
		'PWMSrc': 0,
		'CurrentPWMdata': [0, duty, 20, duty, 65, duty, 70, duty, 100, 100],
	}


def evaluate(*, profile: str, gpus: List[dict], previous_temperature_c: Optional[float] = None) -> dict:
	max_temp = max(value for gpu in gpus for value in gpu['temperatures_c'].values())
	# increase immediately; limit how fast the control temperature decreases
	control_temp = max_temp
	if previous_temperature_c is not None and max_temp < previous_temperature_c:
		control_temp = max(max_temp, previous_temperature_c - MAX_COOLDOWN_STEP_C)
	return {
		'profile': profile,
		'gpus': gpus,
		'hottest_c': max_temp,
		'control_c': control_temp,
		'proposed_duty_percent': duty_for(profile=profile, temperature_c=control_temp),
		'control_enabled': False,
	}


def sample(*, path: Path, root: Path, previous_temperature_c: Optional[float] = None) -> dict:
	try:
		return evaluate(profile=read_profile(path=path), gpus=read_gpus(root=root), previous_temperature_c=previous_temperature_c)
	except (SensorError, OSError, ValueError) as exc:
		return {'control_enabled': False, 'error': str(exc), 'proposed_duty_percent': 100}


def main() -> int:
	parser = argparse.ArgumentParser(description='simulate GPU fan profiles; does not control hardware')
	parser.add_argument('command', choices=(*PROFILES, 'status', 'monitor'))
	args = parser.parse_args()
	path = profile_path()
	if args.command in PROFILES:
		try:
			select_profile(path=path, name=args.command)
		except (OSError, ValueError) as exc:
			print(f'profile not saved: {exc}', file=sys.stderr)
			return 1
		print(f'{args.command} selected; simulation only, BMC fan settings unchanged')
		return 0
	root = Path('/sys/class/hwmon')
	if args.command == 'status':
		result = sample(path=path, root=root)
		print(json.dumps(result, indent=2))
		return 1 if 'error' in result else 0
	logging.basicConfig(level=logging.INFO, format='%(message)s')
	LOG.warning('simulation only; BMC fan settings will not be changed')
	stopping = False

	def stop(_signum: int, _frame: object) -> None:
		nonlocal stopping
		stopping = True

	signal.signal(signal.SIGTERM, stop)
	signal.signal(signal.SIGINT, stop)
	previous: Optional[float] = None
	while not stopping:
		result = sample(path=path, root=root, previous_temperature_c=previous)
		previous = result.get('control_c')
		LOG.info(json.dumps(result, sort_keys=True))
		if not stopping:
			time.sleep(INTERVAL_SECONDS)
	return 0


if __name__ == '__main__':
	sys.exit(main())
