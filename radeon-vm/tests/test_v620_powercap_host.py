#!/usr/bin/env python3
"""Test host V620 cap selection and safe range checking using fake sysfs."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'bin/v620-powercap-host.py'
spec = importlib.util.spec_from_file_location('v620_powercap_host', SCRIPT)
powercap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(powercap)


class PowerCapTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.cards = []
		for index, pci in enumerate(('0000:30:00.0', '0000:43:00.0')):
			hwmon = self.root / f'hwmon{index}'
			device = self.root / 'devices' / pci
			device.mkdir(parents=True)
			hwmon.mkdir()
			(hwmon / 'device').symlink_to(device, target_is_directory=True)
			(hwmon / 'name').write_text('amdgpu\n')
			for name, value in powercap.GPU_IDS.items():
				(device / name).write_text(value + '\n')
			(hwmon / 'power1_cap_min').write_text('120000000\n')
			(hwmon / 'power1_cap_max').write_text('250000000\n')
			(hwmon / 'power1_cap').write_text('250000000\n')
			self.cards.append(hwmon)

	def test_applies_and_reads_back_every_matching_card(self):
		result = powercap.apply_cap(self.root, 200)
		self.assertEqual(result, [
			{'pci': '0000:30:00.0', 'watts': 200},
			{'pci': '0000:43:00.0', 'watts': 200},
		])
		for hwmon in self.cards:
			self.assertEqual((hwmon / 'power1_cap').read_text(), '200000000\n')

	def test_rejects_unsupported_range_before_writing_any_card(self):
		(self.cards[1] / 'power1_cap_min').write_text('250000000\n')
		with self.assertRaisesRegex(powercap.PowerCapError, 'supports 250–250 W'):
			powercap.apply_cap(self.root, 200)
		for hwmon in self.cards:
			self.assertEqual((hwmon / 'power1_cap').read_text(), '250000000\n')

	def test_rejects_non_v620_devices(self):
		device = self.root / 'devices' / '0000:01:00.0'
		hwmon = self.root / 'hwmon2'
		device.mkdir()
		hwmon.mkdir()
		(hwmon / 'device').symlink_to(device, target_is_directory=True)
		(hwmon / 'name').write_text('amdgpu\n')
		(device / 'vendor').write_text('0x1002\n')
		(device / 'device').write_text('0x73a1\n')
		(device / 'subsystem_vendor').write_text('0x1002\n')
		(device / 'subsystem_device').write_text('0xffff\n')
		self.assertEqual(len(powercap.matching_cards(self.root)), 2)

	def test_fails_when_no_v620_is_bound_to_the_host_driver(self):
		with tempfile.TemporaryDirectory() as empty:
			with self.assertRaisesRegex(powercap.PowerCapError, 'no host-driver-bound'):
				powercap.apply_cap(Path(empty), 200)

	def test_rejects_nonpositive_cap(self):
		with self.assertRaisesRegex(powercap.PowerCapError, 'positive integer'):
			powercap.apply_cap(self.root, 0)


if __name__ == '__main__':
	unittest.main()
