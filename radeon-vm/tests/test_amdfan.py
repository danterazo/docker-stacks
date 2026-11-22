#!/usr/bin/env python3
"""Exercise the non-actuating fan-profile prototype with fake sysfs data."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / 'bin' / 'amdfan.py'
spec = importlib.util.spec_from_file_location('amdfan', MODULE)
amdfan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(amdfan)


class FanTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.hwmon = self.root / 'hwmon'
		self.hwmon.mkdir()
		self.state = self.root / 'state' / 'profile'
		for index in range(2):
			self.make_gpu(index)

	def make_gpu(self, index):
		device = self.root / f'0000:0{index + 1}:00.0'
		device.mkdir()
		(device / 'vendor').write_text('0x1002\n')
		(device / 'device').write_text('0x73a1\n')
		monitor = self.hwmon / f'hwmon{index}'
		monitor.mkdir()
		(monitor / 'name').write_text('amdgpu\n')
		(monitor / 'device').symlink_to(device, target_is_directory=True)
		for number, (label, temp) in enumerate((('edge', 35000), ('junction', 45000 + index * 10000), ('mem', 40000)), start=1):
			(monitor / f'temp{number}_label').write_text(label + '\n')
			(monitor / f'temp{number}_input').write_text(str(temp) + '\n')

	def test_reads_both_gpus_and_hottest_sensor(self):
		gpus = amdfan.read_gpus(root=self.hwmon)
		result = amdfan.evaluate(profile='quiet', gpus=gpus)
		self.assertEqual(len(gpus), 2)
		self.assertEqual(result['hottest_c'], 55)
		self.assertEqual(result['proposed_duty_percent'], 28)
		self.assertFalse(result['control_enabled'])

	def test_missing_gpu_or_sensor_is_fail_high_proposal(self):
		(self.hwmon / 'hwmon1' / 'temp2_input').unlink()
		result = amdfan.sample(path=self.state, root=self.hwmon)
		self.assertIn('error', result)
		self.assertEqual(result['proposed_duty_percent'], 100)
		self.assertFalse(result['control_enabled'])

	def test_missing_gpu_fails_closed(self):
		(self.hwmon / 'hwmon1' / 'name').write_text('other')
		with self.assertRaises(amdfan.SensorError):
			amdfan.read_gpus(root=self.hwmon)

	def test_implausible_and_duplicate_labels_fail(self):
		(self.hwmon / 'hwmon0' / 'temp1_input').write_text('999999')
		with self.assertRaises(amdfan.SensorError):
			amdfan.read_gpus(root=self.hwmon)
		(self.hwmon / 'hwmon0' / 'temp1_input').write_text('35000')
		(self.hwmon / 'hwmon0' / 'temp3_label').write_text('edge')
		with self.assertRaises(amdfan.SensorError):
			amdfan.read_gpus(root=self.hwmon)

	def test_profile_selection_and_invalid_state(self):
		self.assertEqual(amdfan.read_profile(path=self.state), 'balanced')
		amdfan.select_profile(path=self.state, name='quiet')
		self.assertEqual(amdfan.read_profile(path=self.state), 'quiet')
		self.state.write_text('broken')
		result = amdfan.sample(path=self.state, root=self.hwmon)
		self.assertEqual(result['proposed_duty_percent'], 100)
		self.assertIn('error', result)

	def test_cli_quiet_sets_only_the_test_profile(self):
		env = dict(os.environ, XDG_STATE_HOME=str(self.root / 'cli-state'))
		result = subprocess.run([sys.executable, '-B', str(MODULE), 'quiet'], env=env, capture_output=True, text=True, check=True)
		self.assertIn('simulation only', result.stdout)
		self.assertEqual((self.root / 'cli-state' / 'amdfan' / 'profile').read_text(), 'quiet\n')

	def test_cooldown_rate_and_full_speed(self):
		gpus = amdfan.read_gpus(root=self.hwmon)
		result = amdfan.evaluate(profile='quiet', gpus=gpus, previous_temperature_c=70)
		self.assertEqual(result['control_c'], 67)
		self.assertEqual(amdfan.duty_for(profile='quiet', temperature_c=80), 100)
		self.assertEqual(amdfan.duty_for(profile='quiet', temperature_c=110), 100)

	def test_fake_bmc_curve_format_and_global_side_effect(self):
		class FakeBMC:
			def __init__(self):
				self.mode = 0
				self.zones = {}

			def put_curve(self, payload):
				self.zones[payload['PWMIndex']] = payload['CurrentPWMdata']
				self.mode = 4

		bmc = FakeBMC()
		bmc.put_curve(amdfan.draft_bmc_curve(duty=10))
		self.assertEqual(bmc.mode, 4)
		self.assertEqual(bmc.zones[2], [0, 10, 20, 10, 65, 10, 70, 10, 100, 100])
		with self.assertRaises(ValueError):
			amdfan.draft_bmc_curve(duty=101)


if __name__ == '__main__':
	unittest.main()
