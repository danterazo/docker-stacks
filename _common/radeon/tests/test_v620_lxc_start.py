#!/usr/bin/env python3
"""Exercise Radeon LXC boot readiness without changing real devices or guests."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / 'bin/v620-lxc-start.py'
spec = importlib.util.spec_from_file_location('v620_lxc_start', SCRIPT)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class BootTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.devices = {
			'dev0': '/dev/kfd,gid=993,mode=0660',
			'dev1': '/dev/dri/card3,gid=44,mode=0660',
			'dev2': '/dev/dri/renderD130,gid=993,mode=0660',
			'dev3': '/dev/dri/card4,gid=44,mode=0660',
			'dev4': '/dev/dri/renderD131,gid=993,mode=0660',
		}

	def make_config(self, vmid, hostname):
		return {
			'hostname': hostname, 'unprivileged': 1, 'onboot': 0, 'digest': f'digest-{vmid}',
			'net0': f'name=eth0,bridge=vmbr0,gw=192.168.10.1,hwaddr=DA:BE:EF:00:01:{vmid-100:02d},ip=192.168.30.{vmid}/16,ip6=auto,type=veth',
			'dev0': '/dev/kfd,gid=993,mode=0660',
			'dev1': '/dev/dri/card1,gid=44,mode=0660',
			'dev2': '/dev/dri/renderD128,gid=993,mode=0660',
			'dev3': '/dev/dri/card2,gid=44,mode=0660',
			'dev4': '/dev/dri/renderD129,gid=993,mode=0660',
		}

	def test_fan_status_requires_recent_verified_bmc(self):
		path = self.root / 'status.json'
		valid = {'updated_monotonic': 95, 'control_enabled': True, 'bmc_reachable': True}
		path.write_text(json.dumps(valid))
		boot.check_fan_status(status_path=path, now=100)
		for change in ({'control_enabled': False}, {'bmc_reachable': False},
				{'readback_degraded': True}, {'updated_monotonic': 70}):
			path.write_text(json.dumps(dict(valid, **change)))
			with self.subTest(change=change), self.assertRaises(boot.ReadinessError):
				boot.check_fan_status(status_path=path, now=100)

	def test_maps_only_devices_linked_to_expected_pci_functions(self):
		pci_root = self.root / 'pci'
		dri = self.root / 'dri'
		by_path = dri / 'by-path'
		by_path.mkdir(parents=True)
		driver = self.root / 'drivers/amdgpu'
		driver.mkdir(parents=True)
		kfd = self.root / 'kfd'
		kfd.touch()
		for index, pci in enumerate(boot.GPUS):
			device = pci_root / pci
			device.mkdir(parents=True)
			for key, value in {'vendor': '0x1002', 'device': '0x73a1',
					'subsystem_vendor': '0x1002', 'subsystem_device': '0x0e34'}.items():
				(device / key).write_text(value)
			(device / 'driver').symlink_to(driver)
			card = dri / f'card{index+1}'
			render = dri / f'renderD{index+128}'
			card.touch()
			render.touch()
			(by_path / f'pci-{pci}-card').symlink_to(card)
			(by_path / f'pci-{pci}-render').symlink_to(render)
		(dri / 'card0').touch()
		with mock.patch.object(boot, 'PCI_ROOT', pci_root), mock.patch.object(boot, 'DRI_ROOT', dri), \
				mock.patch.object(boot, 'KFD', kfd), mock.patch.object(boot.stat, 'S_ISCHR', return_value=True), \
				mock.patch.object(boot.os, 'major', return_value=226):
			mapped = boot.gpu_devices()
		self.assertEqual(len(mapped), 5)
		self.assertNotIn(str(dri / 'card0'), ' '.join(mapped.values()))
		self.assertIn(str(dri / 'card1'), mapped['dev1'])
		self.assertIn(str(dri / 'renderD129'), mapped['dev4'])

	def test_gpu_telemetry_rejects_missing_or_unsafe_cards(self):
		hwmons = self.root / 'hwmon'
		hwmons.mkdir()
		for index, pci in enumerate(boot.GPUS):
			device = self.root / 'devices' / pci
			device.mkdir(parents=True)
			monitor = hwmons / f'hwmon{index}'
			monitor.mkdir()
			(monitor / 'name').write_text('amdgpu\n')
			(monitor / 'device').symlink_to(device)
			for n, label in enumerate(('edge', 'junction', 'mem'), 1):
				(monitor / f'temp{n}_label').write_text(label)
				(monitor / f'temp{n}_input').write_text('35000')
			for key, value in {'power1_cap': '200000000', 'power1_cap_min': '120000000', 'power1_cap_max': '250000000'}.items():
				(monitor / key).write_text(value)
		with mock.patch.object(boot, 'HWMON_ROOT', hwmons):
			self.assertEqual(boot.gpu_caps(), {pci: 200000000 for pci in boot.GPUS})
			(hwmons / 'hwmon1/temp2_input').write_text('90000')
			with self.assertRaisesRegex(boot.ReadinessError, 'unsafe'):
				boot.gpu_caps()
			(hwmons / 'hwmon1/temp2_input').write_text('35000')
			(hwmons / 'hwmon1/power1_cap_min').write_text('250000000')
			with self.assertRaisesRegex(boot.ReadinessError, '120–200'):
				boot.gpu_caps()

	def test_preflight_waits_for_delayed_fan_and_gpu_readiness(self):
		with mock.patch.object(boot, 'command', return_value=''), \
				mock.patch.object(boot, 'check_fan_status', side_effect=[boot.ReadinessError('starting'), None]), \
				mock.patch.object(boot, 'gpu_devices', return_value=self.devices), \
				mock.patch.object(boot, 'gpu_caps', return_value={pci: 200000000 for pci in boot.GPUS}), \
				mock.patch.object(boot.time, 'sleep') as sleep:
			self.assertEqual(boot.ready(timeout=10), self.devices)
			sleep.assert_called_once()

	def test_preflight_timeout_fails_without_starting_guests(self):
		with mock.patch.object(boot, 'command', return_value=''), \
				mock.patch.object(boot, 'check_fan_status', side_effect=boot.ReadinessError('unverified')):
			with self.assertRaisesRegex(boot.ReadinessError, 'timed out'):
				boot.ready(timeout=0)

	def test_guest_config_rejects_privilege_network_and_device_changes(self):
		base = self.make_config(150, 'vllm')
		with mock.patch.object(boot, 'command', return_value=json.dumps(base)):
			self.assertEqual(boot.config(vmid=150, hostname='vllm', devices=self.devices), base)
		for changes in ({'unprivileged': 0}, {'onboot': 1}, {'lock': 'backup'}, {'net0': base['net0'] + ',rate=10'},
				{'dev1': '/dev/dri/card1,gid=44,mode=0666'}, {'dev5': '/dev/dri/card0'}):
			bad = dict(base, **changes)
			with self.subTest(changes=changes), mock.patch.object(boot, 'command', return_value=json.dumps(bad)):
				with self.assertRaises(boot.ReadinessError):
					boot.config(vmid=150, hostname='vllm', devices=self.devices)

	def test_guest_start_updates_stopped_devices_then_starts_in_order(self):
		configs = {150: self.make_config(150, 'vllm'), 151: self.make_config(151, 'llama-cpp')}
		states = {150: 'stopped', 151: 'stopped'}
		caps = {pci: 250000000 for pci in boot.GPUS}
		calls = []
		def fake_command(args, *, timeout=30):
			calls.append(args)
			if args[0] == boot.PVESH:
				vmid = int(args[2].split('/')[4])
				return json.dumps(configs[vmid])
			if args[0] == boot.PCT and args[1] == 'status':
				return 'status: ' + states[int(args[2])]
			if args[0] == boot.PCT and args[1] == 'set':
				vmid = int(args[2])
				self.assertEqual(args[4], configs[vmid]['digest'])
				for i in range(5, len(args), 2):
					configs[vmid][args[i][2:]] = args[i + 1]
				return ''
			if args[0] == boot.PCT and args[1] == 'start':
				states[int(args[2])] = 'running'
				return ''
			if args[1:3] == [str(boot.CAP_HELPER), '--watts']:
				for pci in caps:
					caps[pci] = 200000000
				return ''
			raise AssertionError(args)
		with mock.patch.object(boot, 'command', side_effect=fake_command), \
				mock.patch.object(boot, 'gpu_caps', side_effect=lambda: dict(caps)), \
				mock.patch.object(boot, 'check_fan_status'):
			boot.start_guests(devices=self.devices)
		starts = [args[2] for args in calls if args[:2] == [boot.PCT, 'start']]
		self.assertEqual(starts, ['150', '151'])
		sets = [args for args in calls if args[:2] == [boot.PCT, 'set']]
		self.assertEqual(len(sets), 2)
		self.assertEqual(caps, {pci: 200000000 for pci in boot.GPUS})

	def test_running_guest_with_stale_devices_stops_before_mutation(self):
		configs = {150: self.make_config(150, 'vllm'), 151: self.make_config(151, 'llama-cpp')}
		calls = []
		def fake_command(args, *, timeout=30):
			calls.append(args)
			if args[0] == boot.PVESH:
				return json.dumps(configs[int(args[2].split('/')[4])])
			if args[0] == boot.PCT and args[1] == 'status':
				return 'status: running'
			raise AssertionError(args)
		with mock.patch.object(boot, 'command', side_effect=fake_command):
			with self.assertRaisesRegex(boot.ReadinessError, 'stale'):
				boot.start_guests(devices=self.devices)
		self.assertFalse(any(args[0] == boot.PCT and args[1] in ('set', 'start') for args in calls))

	def test_running_guests_with_current_devices_are_left_untouched(self):
		configs = {150: self.make_config(150, 'vllm'), 151: self.make_config(151, 'llama-cpp')}
		for config in configs.values():
			config.update(self.devices)
		calls = []
		def fake_command(args, *, timeout=30):
			calls.append(args)
			if args[0] == boot.PVESH:
				return json.dumps(configs[int(args[2].split('/')[4])])
			if args[:2] == [boot.PCT, 'status']:
				return 'status: running'
			raise AssertionError(args)
		with mock.patch.object(boot, 'command', side_effect=fake_command), \
				mock.patch.object(boot, 'gpu_caps', return_value={pci: 120000000 for pci in boot.GPUS}), \
				mock.patch.object(boot, 'check_fan_status'):
			boot.start_guests(devices=self.devices)
		self.assertFalse(any(args[0] == boot.PCT and args[1] in ('set', 'start') for args in calls))
		self.assertFalse(any(len(args) > 1 and args[1] == str(boot.CAP_HELPER) for args in calls))

	def test_failed_cap_application_never_starts_either_guest(self):
		configs = {150: self.make_config(150, 'vllm'), 151: self.make_config(151, 'llama-cpp')}
		calls = []
		def fake_command(args, *, timeout=30):
			calls.append(args)
			if args[0] == boot.PVESH:
				return json.dumps(configs[int(args[2].split('/')[4])])
			if args[:2] == [boot.PCT, 'status']:
				return 'status: stopped'
			if args[1:3] == [str(boot.CAP_HELPER), '--watts']:
				raise boot.ReadinessError('cap write failed')
			raise AssertionError(args)
		with mock.patch.object(boot, 'command', side_effect=fake_command), \
				mock.patch.object(boot, 'gpu_caps', return_value={pci: 250000000 for pci in boot.GPUS}):
			with self.assertRaisesRegex(boot.ReadinessError, 'cap write failed'):
				boot.start_guests(devices=self.devices)
		self.assertFalse(any(args[0] == boot.PCT and args[1] in ('set', 'start') for args in calls))

	def test_main_does_not_start_guests_if_readiness_fails(self):
		with mock.patch.object(boot.os, 'geteuid', return_value=0), \
				mock.patch.object(boot.socket, 'gethostname', return_value='kveikur'), \
				mock.patch.object(boot, 'ready', side_effect=boot.ReadinessError('unsafe')), \
				mock.patch.object(boot, 'start_guests') as start, redirect_stderr(io.StringIO()):
			self.assertEqual(boot.main(), 1)
			start.assert_not_called()

	def test_main_rejects_wrong_host_without_actions(self):
		with mock.patch.object(boot.os, 'geteuid', return_value=0), \
				mock.patch.object(boot.socket, 'gethostname', return_value='wrong-host'), \
				mock.patch.object(boot, 'ready') as ready, redirect_stderr(io.StringIO()):
			self.assertEqual(boot.main(), 1)
			ready.assert_not_called()


if __name__ == '__main__':
	unittest.main()
