#!/usr/bin/env python3
"""Exercise GPU fan control with fake sysfs and a fake BMC."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / 'bin' / 'amd-fan.py'
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
		self.pci = self.root / 'pci'
		self.pci.mkdir()
		self.state = self.root / 'state' / 'profile'
		for index in range(2):
			self.make_gpu(index)

	def make_gpu(self, index):
		device = self.root / f'0000:0{index + 1}:00.0'
		device.mkdir()
		(device / 'vendor').write_text('0x1002\n')
		(device / 'device').write_text('0x73a1\n')
		(self.pci / device.name).symlink_to(device, target_is_directory=True)
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
		self.assertEqual(result['proposed_duty_percent'], 5)
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

	def test_unbound_v620s_default_to_quiet_duty(self):
		empty = self.root / 'empty-hwmon'
		empty.mkdir()
		result = amdfan.sample(path=self.state, root=empty, pci_root=self.pci)
		self.assertEqual(result['profile'], 'quiet')
		self.assertEqual(result['proposed_duty_percent'], 5)
		self.assertEqual(result['sensor_state'], 'no-driver-bound-gpus')
		amdfan.select_profile(path=self.state, name='performance')
		result = amdfan.sample(path=self.state, root=empty, pci_root=self.pci)
		self.assertEqual(result['effective_profile'], 'quiet')
		self.assertEqual(result['proposed_duty_percent'], 5)

	def test_zero_readings_with_a_bound_driver_is_not_quiet_fallback(self):
		empty = self.root / 'empty-hwmon'
		empty.mkdir()
		(self.root / '0000:01:00.0' / 'driver').symlink_to('/sys/bus/pci/drivers/amdgpu')
		result = amdfan.sample(path=self.state, root=empty, pci_root=self.pci)
		self.assertEqual(result['proposed_duty_percent'], 100)
		self.assertIn('driver-bound V620', result['error'])

	def test_losing_both_gpus_after_valid_telemetry_fails_high(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 3}
		gpus = amdfan.read_gpus(root=self.hwmon)
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep'), mock.patch.object(amdfan, 'read_temperatures', side_effect=[gpus, []]):
			result = amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(result, 1)
		client.set_duty.assert_called_once_with(duty=5)
		client.full_speed.assert_called_once()

	def test_implausible_and_duplicate_labels_fail(self):
		(self.hwmon / 'hwmon0' / 'temp1_input').write_text('999999')
		with self.assertRaises(amdfan.SensorError):
			amdfan.read_gpus(root=self.hwmon)
		(self.hwmon / 'hwmon0' / 'temp1_input').write_text('35000')
		(self.hwmon / 'hwmon0' / 'temp3_label').write_text('edge')
		with self.assertRaises(amdfan.SensorError):
			amdfan.read_gpus(root=self.hwmon)

	def test_profile_selection_and_invalid_state(self):
		self.assertEqual(amdfan.read_profile(path=self.state), 'quiet')
		amdfan.select_profile(path=self.state, name='full-speed')
		self.assertEqual(amdfan.read_profile(path=self.state), 'full-speed')
		self.state.write_text('broken')
		result = amdfan.sample(path=self.state, root=self.hwmon)
		self.assertEqual(result['proposed_duty_percent'], 100)
		self.assertIn('error', result)

	def test_cli_quiet_sets_only_the_test_profile(self):
		state = {'service_ready': True, 'control_enabled': True, 'profile': 'quiet', 'verified_requested_duty_percent': 5, 'updated_monotonic': float('inf')}
		out = io.StringIO()
		with mock.patch.object(sys, 'argv', ['amd-fan', 'quiet']), mock.patch.object(amdfan, 'PROFILE_PATH', self.state), mock.patch.object(amdfan, 'read_status', return_value=state), contextlib.redirect_stdout(out):
			self.assertEqual(amdfan.main(), 0)
		self.assertIn('quiet active', out.getvalue())
		self.assertEqual(self.state.read_text(), 'quiet\n')

	def test_cli_refuses_profile_change_when_service_unavailable(self):
		with mock.patch.object(sys, 'argv', ['amd-fan', 'quiet']), mock.patch.object(amdfan, 'PROFILE_PATH', self.state), mock.patch.object(amdfan, 'read_status', return_value=None), contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(amdfan.main(), 1)
		self.assertFalse(self.state.exists())

	def test_cooldown_rate_and_full_speed(self):
		gpus = amdfan.read_gpus(root=self.hwmon)
		result = amdfan.evaluate(profile='quiet', gpus=gpus, previous_temperature_c=70)
		self.assertEqual(result['control_c'], 67)
		self.assertEqual(amdfan.duty_for(profile='quiet', temperature_c=80), 60)
		self.assertEqual(amdfan.duty_for(profile='quiet', temperature_c=85), 100)
		self.assertEqual(amdfan.duty_for(profile='quiet', temperature_c=110), 100)

	def test_profiles_are_monotonic_and_keep_minimum_and_headroom(self):
		for profile in amdfan.PROFILES:
			with self.subTest(profile=profile):
				duties = [amdfan.duty_for(profile=profile, temperature_c=temp) for temp in range(101)]
				self.assertEqual(duties, sorted(duties))
				self.assertEqual(min(duties), 5)
				self.assertEqual(duties[85], 100)

	def test_four_profiles_share_an_idle_floor_and_ramp_in_order(self):
		self.assertEqual(amdfan.PROFILE_NAMES, ('quiet', 'balanced', 'performance', 'full-speed'))
		self.assertEqual(amdfan.read_profile(path=self.state), 'quiet')
		for temp in range(101):
			duties = [amdfan.duty_for(profile=profile, temperature_c=temp) for profile in amdfan.PROFILE_NAMES]
			self.assertEqual(duties, sorted(duties))
			self.assertEqual(duties[-1], 100)
			if temp <= 50:
				self.assertEqual(duties[:3], [5, 5, 5])
		self.assertEqual(amdfan.PROFILES['quiet'], [(0, 5), (55, 5), (65, 10), (72, 20), (76, 35), (80, 60), (85, 100)])

	def test_small_decrease_returns_to_idle_floor_after_cooldown(self):
		for profile in amdfan.PROFILES:
			with self.subTest(profile=profile):
				self.assertFalse(amdfan.should_update_duty(profile=profile, duty=5, last_duty=6, elapsed=0))
				self.assertTrue(amdfan.should_update_duty(profile=profile, duty=5, last_duty=6, elapsed=amdfan.MAX_UPDATE_DELAY_SECONDS))
				self.assertFalse(amdfan.should_update_duty(profile=profile, duty=5, last_duty=5, elapsed=amdfan.MAX_UPDATE_DELAY_SECONDS))

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

	def test_bmc_authentication_and_verified_writes(self):
		class Response(io.BytesIO):
			def __enter__(self):
				return self

			def __exit__(self, *_args):
				self.close()

		class FakeTransport:
			def __init__(self):
				self.mode = 0
				self.points = [0, 20, 20, 20, 65, 20, 70, 20, 100, 100]
				self.headers = []

			def open(self, request, timeout):
				self.assert_timeout(timeout)
				path = request.full_url.removeprefix(amdfan.BMC_URL)
				self.headers.append(dict(request.header_items()))
				if path == '/api/session':
					data = {'ok': 0, 'CSRFToken': 'test-token'}
				elif path == '/api/fanctrl/PWM':
					if request.method == 'PUT':
						body = json.loads(request.data)
						self.points = body['CurrentPWMdata']
						self.mode = 4
					data = [{}, {}, {'PWMName': 'Zone3(CHA_FAN 2)', 'CurrentPWMdata': [{'Temp': self.points[i], 'Duty': self.points[i + 1]} for i in range(0, 10, 2)]}]
				elif path == '/api/fanctrl/mode':
					if request.method == 'PUT':
						self.mode = json.loads(request.data)['FanMode']
					data = {'FanMode': self.mode}
				else:
					raise AssertionError(path)
				return Response(json.dumps(data).encode())

			@staticmethod
			def assert_timeout(timeout):
				if timeout != 5:
					raise AssertionError('missing bounded timeout')

		transport = FakeTransport()
		client = amdfan.BmcClient(username='test-user', password='test-password', opener=transport)
		client.login()
		client.set_duty(duty=10)
		self.assertEqual(transport.points, [0, 10, 20, 10, 65, 10, 70, 10, 100, 100])
		self.assertEqual(transport.mode, 4)
		self.assertEqual(transport.headers[1]['X-csrftoken'], 'test-token')
		client.full_speed()
		self.assertEqual(transport.mode, 3)

	def test_vm_credential_uses_user_home_without_systemd_loading_it(self):
		creds = self.root / '.creds'
		creds.mkdir()
		(creds / 'kveikur-bmc').write_text(json.dumps({'username': 'dummy-user', 'password': 'dummy-password'}))
		with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(amdfan.Path, 'home', return_value=self.root):
			client = amdfan.bmc_from_credential()
		self.assertEqual(client.username, 'dummy-user')
		self.assertEqual(client.password, 'dummy-password')

	def test_host_systemd_credential_takes_precedence(self):
		creds = self.root / 'credentials'
		creds.mkdir()
		(creds / 'bmc.json').write_text(json.dumps({'username': 'dummy-host', 'password': 'dummy-password'}))
		with mock.patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': str(creds)}, clear=True):
			client = amdfan.bmc_from_credential()
		self.assertEqual(client.username, 'dummy-host')

	def test_vm_credential_symlink_is_rejected(self):
		creds = self.root / '.creds'
		creds.mkdir()
		(creds / 'target').write_text('{}')
		(creds / 'kveikur-bmc').symlink_to(creds / 'target')
		with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(amdfan.Path, 'home', return_value=self.root):
			with self.assertRaises(amdfan.BmcError):
				amdfan.bmc_from_credential()

	def test_bmc_refuses_write_for_unexpected_zone(self):
		client = mock.Mock()
		client.request.return_value = [{}, {}, {'PWMName': 'wrong header'}]
		with self.assertRaises(amdfan.BmcError):
			amdfan.BmcClient.set_duty(client, duty=10)
		self.assertEqual(client.request.call_count, 1)

	def test_transient_reads_and_uncertain_writes_are_classified(self):
		client = amdfan.BmcClient(username='dummy', password='dummy', opener=mock.Mock())
		path = '/api/fanctrl/PWM'
		client.opener.open.side_effect = amdfan.urllib.error.URLError(TimeoutError())
		with self.assertRaisesRegex(amdfan.BmcReadTimeout, 'TimeoutError'):
			client.request(path=path)
		with self.assertRaises(amdfan.BmcError) as caught:
			client.request(path=path, method='PUT', body={})
		self.assertNotIsInstance(caught.exception, amdfan.BmcTransientReadError)
		self.assertIsInstance(caught.exception, amdfan.BmcTransientError)
		for status, subclass in ((504, amdfan.BmcReadTimeout), (503, amdfan.BmcTransientReadError), (401, amdfan.BmcError)):
			client.opener.open.side_effect = amdfan.urllib.error.HTTPError(amdfan.BMC_URL + path, status, 'dummy', {}, None)
			with self.assertRaisesRegex(amdfan.BmcError, f'HTTP {status}') as caught:
				client.request(path=path)
			self.assertIs(type(caught.exception), subclass)
		for method in ('GET', 'POST', 'PUT'):
			for status in (408, 500, 502, 503, 504):
				client.opener.open.side_effect = amdfan.urllib.error.HTTPError(amdfan.BMC_URL + path, status, 'dummy', {}, None)
				with self.subTest(method=method, status=status), self.assertRaises(amdfan.BmcTransientError):
					client.request(path=path, method=method, body={})

	def test_transient_read_gets_one_retry_without_writing(self):
		client = mock.Mock()
		transient = amdfan.BmcTransientReadError('HTTP 503')
		for outcomes in ([transient, None], [transient, transient], [transient, amdfan.BmcError('mode mismatch')]):
			with self.subTest(outcomes=outcomes), mock.patch.object(amdfan.time, 'sleep') as sleep:
				client.reset_mock()
				client.verify_duty.side_effect = outcomes
				if outcomes[1] is None:
					amdfan.verify_running_setting(client=client, duty=10, full_speed=False)
				else:
					with self.assertRaises(amdfan.BmcError):
						amdfan.verify_running_setting(client=client, duty=10, full_speed=False)
				self.assertEqual(client.method_calls, [mock.call.verify_duty(duty=10)] * 2)
				sleep.assert_called_once_with(amdfan.READ_RETRY_DELAY_SECONDS)

	def test_monitor_recovers_after_repeated_transient_reads(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 3}
		transient = amdfan.BmcTransientReadError('HTTP 503')
		client.verify_duty.side_effect = [transient, transient, None]
		status = self.root / 'status.json'
		steps = iter(('normal', 'outage', 'recovered'))
		def inspect(seconds):
			if seconds == amdfan.READ_RETRY_DELAY_SECONDS:
				return
			state = json.loads(status.read_text())
			step = next(steps)
			if step == 'outage':
				self.assertTrue(state['service_ready'])
				self.assertFalse(state['control_enabled'])
				self.assertEqual(state['recovery_profile'], 'quiet')
				client.full_speed.assert_not_called()
			elif step == 'recovered':
				self.assertTrue(state['control_enabled'])
				self.assertEqual(state['profile'], 'quiet')
				raise KeyboardInterrupt
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=inspect):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=status, client=client)
		self.assertEqual(client.login.call_count, 2)
		self.assertEqual(client.set_duty.call_args_list, [mock.call(duty=5)] * 2)
		client.full_speed.assert_called_once()

	def test_read_timeout_holds_applied_profile_then_resumes(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 3}
		timeout = amdfan.BmcReadTimeout('HTTP 504')
		client.verify_duty.side_effect = [timeout, timeout, None]
		status = self.root / 'status.json'
		steps = iter(('request', 'hold', 'recovered'))

		def inspect(seconds):
			if seconds == amdfan.READ_RETRY_DELAY_SECONDS:
				return
			state = json.loads(status.read_text())
			step = next(steps)
			if step == 'request':
				amdfan.select_profile(path=self.state, name='performance')
			elif step == 'hold':
				self.assertTrue(state['readback_degraded'])
				self.assertFalse(state['control_enabled'])
				self.assertEqual(state['profile'], 'quiet')
				self.assertEqual(amdfan.read_profile(path=self.state), 'quiet')
				self.assertEqual(state['last_verified_duty_percent'], 5)
				client.set_duty.assert_called_once_with(duty=5)
				client.full_speed.assert_not_called()
			else:
				self.assertNotIn('readback_degraded', state)
				self.assertEqual(state['profile'], 'quiet')
				self.assertEqual(state['verified_requested_duty_percent'], 5)
				raise KeyboardInterrupt

		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=inspect):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=status, client=client)
		self.assertEqual(client.set_duty.call_args_list, [mock.call(duty=5)] * 2)

	def test_long_or_hot_outage_keeps_monitoring_but_reports_unverified_cooling(self):
		for hot in (False, True):
			with self.subTest(hot=hot):
				client = mock.Mock()
				client.request.return_value = {'FanMode': 3}
				client.verify_duty.side_effect = amdfan.BmcReadTimeout('HTTP 504')
				now = 0.0
				gpu_temp = self.hwmon / 'hwmon1' / 'temp2_input'
				gpu_temp.write_text('55000')

				def advance(seconds):
					nonlocal now
					now += seconds
					if hot:
						gpu_temp.write_text(str(amdfan.BMC_OUTAGE_WARNING_TEMP_C * 1000))
					if now >= 45:
						state = json.loads((self.root / 'status.json').read_text())
						self.assertFalse(state['control_enabled'])
						self.assertTrue(state['service_ready'])
						self.assertEqual(state['recovery_profile'], 'quiet')
						client.full_speed.assert_not_called()
						raise KeyboardInterrupt

				with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=advance), mock.patch.object(amdfan.time, 'monotonic', side_effect=lambda: now), mock.patch.object(amdfan.LOG, 'critical') as critical:
					with self.assertRaises(KeyboardInterrupt):
						amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
				critical.assert_called()
				client.set_duty.assert_called_once_with(duty=5)
				client.full_speed.assert_called_once()

	def test_startup_login_blip_reports_alive_and_recovers_to_quiet(self):
		amdfan.select_profile(path=self.state, name='performance')
		client = mock.Mock()
		client.login.side_effect = [amdfan.BmcTransientError('HTTP 502'), None]
		client.request.return_value = {'FanMode': 4}
		status = self.root / 'status.json'
		steps = iter(('outage', 'recovered'))
		def inspect(seconds):
			state = json.loads(status.read_text())
			if next(steps) == 'outage':
				self.assertTrue(state['service_ready'])
				self.assertFalse(state['control_enabled'])
				self.assertEqual(state['profile'], 'quiet')
				client.set_duty.assert_not_called()
				client.full_speed.assert_not_called()
			else:
				self.assertTrue(state['control_enabled'])
				self.assertEqual(state['profile'], 'quiet')
				raise KeyboardInterrupt
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=inspect), mock.patch.object(amdfan, 'notify') as notify:
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=status, client=client)
		self.assertIn(mock.call(message='READY=1'), notify.call_args_list)
		self.assertEqual(client.login.call_count, 2)
		client.set_duty.assert_called_once_with(duty=5)

	def test_uncertain_write_is_reapplied_not_compared_to_stale_curve(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 4}
		client.set_duty.side_effect = [None, amdfan.BmcTransientError('HTTP 502'), None]
		status = self.root / 'status.json'
		steps = iter(('normal', 'uncertain', 'recovered'))
		def inspect(seconds):
			state = json.loads(status.read_text())
			step = next(steps)
			if step == 'normal':
				amdfan.select_profile(path=self.state, name='performance')
			elif step == 'uncertain':
				self.assertFalse(state['control_enabled'])
				self.assertTrue(state['setting_uncertain'])
				self.assertEqual(state['profile'], 'quiet')
				client.full_speed.assert_not_called()
			else:
				self.assertTrue(state['control_enabled'])
				self.assertEqual(state['verified_requested_duty_percent'], 5)
				raise KeyboardInterrupt
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=inspect):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=status, client=client)
		client.verify_duty.assert_called_once_with(duty=5)
		self.assertEqual(client.set_duty.call_args_list, [mock.call(duty=5), mock.call(duty=12), mock.call(duty=5)])

	def test_sensor_loss_during_bmc_outage_still_fails_high(self):
		client = mock.Mock()
		client.login.side_effect = amdfan.BmcTransientError('HTTP 502')
		(self.hwmon / 'hwmon1' / 'temp2_input').unlink()
		with mock.patch.object(amdfan.signal, 'signal'):
			result = amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(result, 1)
		client.full_speed.assert_called_once()

	def test_monitor_requests_full_speed_when_sensor_missing(self):
		class FakeBMC:
			def __init__(self):
				self.full = 0

			def login(self):
				pass

			def request(self, **_kwargs):
				return {'FanMode': 0}

			def full_speed(self):
				self.full += 1

		(self.hwmon / 'hwmon1' / 'temp2_input').unlink()
		client = FakeBMC()
		with mock.patch.object(amdfan.signal, 'signal'):
			result = amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(result, 1)
		self.assertEqual(client.full, 1)
		self.assertFalse(json.loads((self.root / 'status.json').read_text())['control_enabled'])

	def test_monitor_does_not_override_external_full_speed(self):
		class FakeBMC:
			def __init__(self):
				self.duties = []
				self.full = 0

			def login(self):
				pass

			def request(self, **_kwargs):
				return {'FanMode': 0}

			def set_duty(self, *, duty):
				self.duties.append(duty)

			def verify_duty(self, *, duty):
				raise amdfan.BmcError('external full-speed override')

			def full_speed(self):
				self.full += 1

		client = FakeBMC()
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', return_value=None):
			result = amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(result, 1)
		self.assertEqual(len(client.duties), 1)
		self.assertEqual(client.full, 1)

	def test_monitor_falls_back_after_unexpected_exit(self):
		class FakeBMC:
			def __init__(self):
				self.duties = []
				self.full = 0

			def login(self):
				pass

			def request(self, **_kwargs):
				return {'FanMode': 0}

			def set_duty(self, *, duty):
				self.duties.append(duty)

			def full_speed(self):
				self.full += 1

		client = FakeBMC()
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=KeyboardInterrupt):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(len(client.duties), 1)
		self.assertEqual(client.full, 1)

	def test_orderly_restart_leaves_bmc_setting_unchanged(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 4}
		handlers = {}

		def register(signum, handler):
			handlers[signum] = handler

		def stop_monitor(_seconds):
			handlers[amdfan.signal.SIGTERM](amdfan.signal.SIGTERM, None)

		with mock.patch.object(amdfan.signal, 'signal', side_effect=register), mock.patch.object(amdfan.time, 'sleep', side_effect=stop_monitor):
			result = amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(result, 0)
		client.set_duty.assert_called_once_with(duty=5)
		client.full_speed.assert_not_called()

	def test_guest_fan_health_requires_successful_completed_probe(self):
		for response, expected in (({'exited': 1, 'exitcode': 0}, True),
			({'exited': 1, 'exitcode': 1}, False), ({'pid': 42}, False)):
			with self.subTest(response=response), mock.patch.object(amdfan.subprocess, 'run') as run:
				run.return_value.returncode = 0
				run.return_value.stdout = json.dumps(response).encode()
				self.assertEqual(amdfan.guest_fan_healthy(), expected)
		with mock.patch.object(amdfan.subprocess, 'run', side_effect=amdfan.subprocess.TimeoutExpired('qm', 10)):
			self.assertFalse(amdfan.guest_fan_healthy())

	def test_boot_defaults_to_quiet_even_when_bmc_starts_at_full_speed(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 3}
		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=KeyboardInterrupt):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		client.set_duty.assert_called_once_with(duty=5)
		client.full_speed.assert_called_once()

	def test_full_speed_profile_uses_bmc_mode_and_requires_no_gpu_sensors(self):
		amdfan.select_profile(path=self.state, name='full-speed')
		client = mock.Mock()
		client.request.return_value = {'FanMode': 4}
		status = self.root / 'status.json'

		def inspect_status(_seconds):
			result = json.loads(status.read_text())
			self.assertEqual(result['profile'], 'full-speed')
			self.assertEqual(result['bmc_mode'], 'full-speed')
			self.assertEqual(result['verified_requested_duty_percent'], 100)
			raise KeyboardInterrupt

		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=inspect_status):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.root / 'missing', status_path=status, client=client)
		client.set_duty.assert_not_called()
		self.assertEqual(client.full_speed.call_count, 2)

	def test_switches_between_adaptive_and_full_speed_profiles(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 3}
		profiles = iter(('full-speed', 'quiet'))

		def change_profile(_seconds):
			try:
				name = next(profiles)
			except StopIteration:
				raise KeyboardInterrupt from None
			amdfan.select_profile(path=self.state, name=name)

		with mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep', side_effect=change_profile):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_monitor(path=self.state, root=self.hwmon, status_path=self.root / 'status.json', client=client)
		self.assertEqual(client.method_calls, [
			mock.call.login(), mock.call.request(path='/api/fanctrl/mode'),
			mock.call.set_duty(duty=5), mock.call.verify_duty(duty=5),
			mock.call.full_speed(), mock.call.verify_full_speed(),
			mock.call.set_duty(duty=5), mock.call.full_speed(),
		])

	def test_full_speed_override_is_verified(self):
		client = amdfan.BmcClient(username='dummy', password='dummy')
		client.request = mock.Mock(side_effect=[{}, {'FanMode': 0}])
		with self.assertRaises(amdfan.BmcError):
			amdfan.BmcClient.full_speed(client)
		client.request.assert_any_call(path='/api/fanctrl/mode', method='PUT', body={'FanMode': 3})

	def test_host_watchdog_waits_for_three_failures_and_never_resumes_quiet(self):
		client = mock.Mock()
		client.request.return_value = {'FanMode': 4}
		guard = amdfan.HostWatchdog(client=client)
		guard.check(healthy=False)
		guard.check(healthy=False)
		client.full_speed.assert_not_called()
		guard.check(healthy=True)
		guard.check(healthy=False)
		guard.check(healthy=False)
		client.full_speed.assert_not_called()
		guard.check(healthy=False)
		client.full_speed.assert_called_once()
		client.request.return_value = {'FanMode': 3}
		guard.check(healthy=False)
		guard.check(healthy=True)
		client.full_speed.assert_called_once()

	def test_host_watchdog_reports_bmc_failure_without_switching_quiet(self):
		client = mock.Mock()
		client.login.side_effect = amdfan.BmcError('connection failed')
		guard = amdfan.HostWatchdog(client=client)
		for _ in range(3):
			guard.check(healthy=False)
		client.full_speed.assert_not_called()
		self.assertFalse(guard.logged_in)

	def test_host_watchdog_does_not_report_ready_without_bmc_auth(self):
		client = mock.Mock()
		client.login.side_effect = amdfan.BmcError('authentication failed')
		with mock.patch.object(amdfan.os, 'geteuid', return_value=0), mock.patch.object(amdfan.socket, 'gethostname', return_value='kveikur'), mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan, 'notify') as notify:
			self.assertEqual(amdfan.run_host_watchdog(client=client), 1)
			notify.assert_not_called()

	def test_host_watchdog_retries_transient_startup_failure(self):
		client = mock.Mock()
		client.login.side_effect = [amdfan.BmcTransientError('timeout'), None]
		client.request.return_value = {'FanMode': 4}
		with mock.patch.object(amdfan.os, 'geteuid', return_value=0), mock.patch.object(amdfan.socket, 'gethostname', return_value='kveikur'), mock.patch.object(amdfan.signal, 'signal'), mock.patch.object(amdfan.time, 'sleep'), mock.patch.object(amdfan, 'notify'), mock.patch.object(amdfan, 'guest_fan_healthy', side_effect=KeyboardInterrupt):
			with self.assertRaises(KeyboardInterrupt):
				amdfan.run_host_watchdog(client=client)
		self.assertEqual(client.login.call_count, 2)


if __name__ == '__main__':
	unittest.main()
