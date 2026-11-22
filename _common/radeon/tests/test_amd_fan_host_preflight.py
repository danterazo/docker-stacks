#!/usr/bin/env python3
"""Exercise the host preflight without accessing GPU hardware."""

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / 'bin' / 'amd-fan-host-preflight.py'
spec = importlib.util.spec_from_file_location('amd_fan_host_preflight', MODULE)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class HostPreflightTests(unittest.TestCase):
	def test_uses_dashed_controller_filename(self):
		self.assertEqual(preflight.controller_path.name, 'amd-fan.py')
		self.assertTrue(callable(preflight.controller.read_gpus))

	def test_succeeds_for_expected_cards(self):
		gpus = [{'pci': '0000:01:00.0'}, {'pci': '0000:02:00.0'}]
		with mock.patch.object(preflight.controller, 'read_gpus', return_value=gpus), contextlib.redirect_stdout(io.StringIO()) as output:
			self.assertEqual(preflight.main(), 0)
		self.assertIn('0000:01:00.0, 0000:02:00.0', output.getvalue())

	def test_waits_for_delayed_host_gpu_sensors(self):
		gpus = [{'pci': '0000:30:00.0'}, {'pci': '0000:43:00.0'}]
		with mock.patch.object(preflight.controller, 'read_gpus', side_effect=[preflight.controller.SensorError('not ready'), gpus]), \
				mock.patch.object(preflight.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()) as output:
			self.assertEqual(preflight.main(timeout=10), 0)
		self.assertIn('0000:30:00.0, 0000:43:00.0', output.getvalue())
		sleep.assert_called_once()

	def test_reports_sensor_failure(self):
		with mock.patch.object(preflight.controller, 'read_gpus', side_effect=preflight.controller.SensorError('missing')), contextlib.redirect_stderr(io.StringIO()) as output:
			self.assertEqual(preflight.main(timeout=0), 1)
		self.assertIn('missing', output.getvalue())

	def test_rejects_unexpected_count(self):
		with mock.patch.object(preflight.controller, 'read_gpus', return_value=[{'pci': '0000:01:00.0'}]), contextlib.redirect_stderr(io.StringIO()) as output:
			self.assertEqual(preflight.main(timeout=0), 1)
		self.assertIn('Expected 2 V620 GPUs, found 1', output.getvalue())


if __name__ == '__main__':
	unittest.main()
