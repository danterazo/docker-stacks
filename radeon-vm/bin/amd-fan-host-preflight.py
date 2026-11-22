#!/usr/bin/env python3
"""Refuse host fan monitoring until all expected V620 sensors are present."""

import importlib.util
import sys
from pathlib import Path

controller_path = Path(__file__).with_name('amd-fan.py')
spec = importlib.util.spec_from_file_location('amd_fan', controller_path)
if spec is None or spec.loader is None:
	raise ImportError(f'Cannot load fan controller from {controller_path}')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def main() -> int:
	try:
		gpus = controller.read_gpus(root=Path('/sys/class/hwmon'), allow_empty=False)
	except (OSError, controller.SensorError) as exc:
		print(f'Host GPU fan control preflight failed: {exc}', file=sys.stderr)
		return 1
	if len(gpus) != controller.EXPECTED_GPUS:
		print(f'Expected {controller.EXPECTED_GPUS} V620 GPUs, found {len(gpus)}', file=sys.stderr)
		return 1
	print('Host GPU fan telemetry ready for: ' + ', '.join(gpu['pci'] for gpu in gpus))
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
