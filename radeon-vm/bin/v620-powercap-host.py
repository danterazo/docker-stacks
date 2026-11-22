#!/usr/bin/env python3
"""Set power caps on host-owned Radeon Pro V620 cards through hwmon."""

import argparse
from pathlib import Path
from typing import Dict, List


HWMON_ROOT = Path('/sys/class/hwmon')
GPU_IDS = {
	'vendor': '0x1002',
	'device': '0x73a1',
	'subsystem_vendor': '0x1002',
	'subsystem_device': '0x0e34',
}
MICROWATTS_PER_WATT = 1_000_000


class PowerCapError(RuntimeError):
	"""A V620 cap could not be applied and verified safely."""


def read(path: Path) -> str:
	try:
		return path.read_text(encoding='ascii').strip()
	except OSError as exc:
		raise PowerCapError(f'cannot read {path}: {exc}') from exc


def matching_cards(root: Path) -> List[Dict[str, Path]]:
	cards: Dict[str, Dict[str, Path]] = {}
	try:
		hwmons = sorted(root.glob('hwmon*'))
	except OSError as exc:
		raise PowerCapError(f'cannot enumerate {root}: {exc}') from exc
	for hwmon in hwmons:
		if not hwmon.is_dir():
			continue
		try:
			if read(hwmon / 'name') != 'amdgpu':
				continue
		except PowerCapError:
			continue
		device = hwmon / 'device'
		if not device.exists():
			continue
		if any(read(device / attr) != value for attr, value in GPU_IDS.items()):
			continue
		try:
			pci = device.resolve(strict=True).name
		except OSError as exc:
			raise PowerCapError(f'cannot resolve V620 PCI device at {device}: {exc}') from exc
		if pci in cards:
			raise PowerCapError(f'multiple hwmon power interfaces found for {pci}')
		paths = {name: hwmon / name for name in ('power1_cap', 'power1_cap_min', 'power1_cap_max')}
		missing = [str(path) for path in paths.values() if not path.is_file()]
		if missing:
			raise PowerCapError(f'V620 {pci} is missing power-cap controls: {", ".join(missing)}')
		cards[pci] = paths
	if not cards:
		raise PowerCapError('no host-driver-bound Radeon Pro V620 cards with power-cap controls found')
	return [dict(pci=pci, **paths) for pci, paths in sorted(cards.items())]


def apply_cap(root: Path, watts: int) -> List[Dict[str, int]]:
	if type(watts) is not int or watts <= 0:
		raise PowerCapError('cap must be a positive integer watt value')
	cards = matching_cards(root)
	requested = watts * MICROWATTS_PER_WATT
	originals: Dict[str, int] = {}
	for card in cards:
		try:
			minimum = int(read(card['power1_cap_min']))
			maximum = int(read(card['power1_cap_max']))
			originals[card['pci']] = int(read(card['power1_cap']))
		except ValueError as exc:
			raise PowerCapError(f'invalid power-cap value for {card["pci"]}') from exc
		if minimum > maximum or not minimum <= requested <= maximum:
			raise PowerCapError(
				f'{card["pci"]} supports {minimum // MICROWATTS_PER_WATT}–'
				f'{maximum // MICROWATTS_PER_WATT} W; requested {watts} W'
			)

	attempted: List[Dict[str, Path]] = []
	try:
		for card in cards:
			attempted.append(card)
			card['power1_cap'].write_text(f'{requested}\n', encoding='ascii')
		for card in cards:
			actual = int(read(card['power1_cap']))
			if actual != requested:
				raise PowerCapError(
					f'{card["pci"]} read back {actual} µW, expected {requested} µW'
				)
	except (OSError, ValueError, PowerCapError) as exc:
		rollback_errors = []
		for card in reversed(attempted):
			try:
				card['power1_cap'].write_text(f'{originals[card["pci"]]}\n', encoding='ascii')
			except OSError as rollback_error:
				rollback_errors.append(f'{card["pci"]}: {rollback_error}')
		if rollback_errors:
			raise PowerCapError(f'{exc}; rollback also failed for {", ".join(rollback_errors)}') from exc
		if isinstance(exc, PowerCapError):
			raise
		raise PowerCapError(f'power-cap write failed: {exc}') from exc

	return [dict(pci=card['pci'], watts=watts) for card in cards]


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--watts', type=int, required=True,
		help='requested cap in watts; must be within every card range')
	args = parser.parse_args()
	try:
		for card in apply_cap(HWMON_ROOT, args.watts):
			print(f'{card["pci"]}: {card["watts"]} W applied and read back')
	except PowerCapError as exc:
		parser.exit(1, f'V620 power cap: {exc}\n')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
