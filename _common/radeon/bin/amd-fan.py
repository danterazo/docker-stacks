#!/usr/bin/env python3
"""Control the GPU fan hub using Radeon temperatures and the ASUS BMC."""

import argparse
import errno
import http.client
import http.cookiejar
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# provisional points use the hottest edge, junction or memory sensor in Celsius
# verify every blower starts at the minimum duty and validate under sustained load
PROFILES: Dict[str, List[Tuple[int, int]]] = {
	'quiet': [(0, 5), (55, 5), (60, 5), (65, 8), (70, 10), (72, 12), (75, 16), (76, 20),
		(78, 27), (80, 35), (81, 40), (82, 48), (83, 60), (84, 78), (85, 100)],
	'balanced': [(0, 5), (53, 5), (55, 7), (60, 10), (65, 16), (70, 22), (72, 28), (75, 38),
		(76, 43), (78, 54), (80, 65), (81, 70), (82, 76), (83, 83), (84, 91), (85, 100)],
	'performance': [(0, 5), (50, 5), (55, 9), (60, 15), (65, 22), (70, 30), (72, 38), (74, 45),
		(76, 55), (77, 63), (78, 70), (80, 78), (81, 82), (82, 87), (83, 91), (84, 96), (85, 100)],
}
FULL_SPEED_PROFILE = 'full-speed'
PROFILE_NAMES = (*PROFILES, FULL_SPEED_PROFILE)
EXPECTED_GPUS = 2
REQUIRED_LABELS = ('edge', 'junction', 'mem')
GPU_VENDOR = '0x1002'
GPU_DEVICE = '0x73a1'
INTERVAL_SECONDS = 5
MAX_COOLDOWN_STEP_C = 3
DEFAULT_PROFILE = 'quiet'
BMC_URL = 'https://kveikur.samskeyti.net'
STATUS_PATH = Path('/run/amd-fan/status.json')
PROFILE_PATH = STATUS_PATH.with_name('profile')
PCI_ROOT = Path('/sys/bus/pci/devices')
CREDENTIAL_NAME = 'bmc.json'
FULL_SPEED_MODE = 3
CUSTOM_MODE = 4
MAX_UPDATE_DELAY_SECONDS = 20
MIN_DUTY_CHANGE = 3
HOST_POLL_SECONDS = 10
HOST_FAILURE_LIMIT = 3
READ_RETRY_DELAY_SECONDS = 0.5
BMC_OUTAGE_WARNING_SECONDS = 30
BMC_OUTAGE_WARNING_TEMP_C = 75
LOG = logging.getLogger('amd-fan')


class SensorError(Exception):
	"""An expected GPU or temperature reading is unavailable."""


class BmcError(Exception):
	"""The BMC request or its verification failed."""


class BmcTransientError(BmcError):
	"""A temporary BMC transport/server failure; a write may have reached the BMC."""


class BmcTransientReadError(BmcTransientError):
	"""A BMC read failed in a way that may clear on retry."""


class BmcReadTimeout(BmcTransientReadError):
	"""The last BMC setting could not be checked before the read timed out."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		raise BmcError('BMC redirect refused')


class BmcClient:
	def __init__(self, *, username: str, password: str, opener=None):
		self.username = username
		self.password = password
		self.csrf: Optional[str] = None
		self.opener = opener or urllib.request.build_opener(
			NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
		)

	def request(self, *, path: str, method: str = 'GET', body: Optional[dict] = None) -> Any:
		headers = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
		if self.csrf:
			headers['X-CSRFTOKEN'] = self.csrf
		data = None
		if body is not None:
			if path == '/api/session':
				data = urllib.parse.urlencode(body).encode()
				headers['Content-Type'] = 'application/x-www-form-urlencoded'
			else:
				data = json.dumps(body).encode()
				headers['Content-Type'] = 'application/json'
		request = urllib.request.Request(BMC_URL + path, data=data, headers=headers, method=method)
		try:
			with self.opener.open(request, timeout=5) as response:
				return json.load(response)
		# log only the HTTP status or error type, never bodies or credentials
		except urllib.error.HTTPError as exc:
			error = BmcError
			if exc.code in (408, 500, 502, 503, 504):
				error = BmcTransientError
				if method == 'GET':
					error = BmcReadTimeout if exc.code in (408, 504) else BmcTransientReadError
			exc.close()
			raise error(f'BMC {method} {path} failed: HTTP {exc.code}') from exc
		except (OSError, ValueError, http.client.HTTPException) as exc:
			cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
			transient = (isinstance(cause, (TimeoutError, ConnectionError, http.client.IncompleteRead)) or
				(isinstance(cause, socket.gaierror) and cause.errno == socket.EAI_AGAIN) or
				(isinstance(cause, OSError) and cause.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH)))
			error = BmcTransientError if transient else BmcError
			if method == 'GET' and transient:
				error = BmcTransientReadError
			if method == 'GET' and isinstance(cause, TimeoutError):
				error = BmcReadTimeout
			raise error(f'BMC {method} {path} failed: {type(cause).__name__}') from exc

	def login(self) -> None:
		self.csrf = None
		response = self.request(path='/api/session', method='POST', body={'username': self.username, 'password': self.password})
		if not isinstance(response, dict) or response.get('ok') != 0 or not isinstance(response.get('CSRFToken'), str) or not response['CSRFToken']:
			raise BmcError('BMC login failed')
		self.csrf = response['CSRFToken']

	def verify_duty(self, *, duty: int) -> None:
		zones = self.request(path='/api/fanctrl/PWM')
		if not isinstance(zones, list) or len(zones) < 3 or not isinstance(zones[2], dict) or zones[2].get('PWMName') != 'Zone3(CHA_FAN 2)':
			raise BmcError('BMC fan zone does not match CHA_FAN2')
		payload = draft_bmc_curve(duty=duty)
		mode = self.request(path='/api/fanctrl/mode')
		try:
			actual = [int(value) for point in zones[2]['CurrentPWMdata'] for value in (point['Temp'], point['Duty'])]
		except (KeyError, IndexError, TypeError, ValueError) as exc:
			raise BmcError('BMC fan curve readback invalid') from exc
		if actual != payload['CurrentPWMdata'] or not isinstance(mode, dict) or mode.get('FanMode') != CUSTOM_MODE:
			raise BmcError('BMC fan curve or mode readback mismatch')

	def set_duty(self, *, duty: int) -> None:
		zones = self.request(path='/api/fanctrl/PWM')
		if not isinstance(zones, list) or len(zones) < 3 or not isinstance(zones[2], dict) or zones[2].get('PWMName') != 'Zone3(CHA_FAN 2)':
			raise BmcError('BMC fan zone does not match CHA_FAN2')
		self.request(path='/api/fanctrl/PWM', method='PUT', body=draft_bmc_curve(duty=duty))
		self.verify_duty(duty=duty)

	def full_speed(self) -> None:
		self.request(path='/api/fanctrl/mode', method='PUT', body={'FanMode': FULL_SPEED_MODE})
		self.verify_full_speed()

	def verify_full_speed(self) -> None:
		mode = self.request(path='/api/fanctrl/mode')
		if not isinstance(mode, dict) or mode.get('FanMode') != FULL_SPEED_MODE:
			raise BmcError('BMC full-speed mode readback mismatch')


def verify_running_setting(*, client: BmcClient, duty: int, full_speed: bool) -> None:
	def verify() -> None:
		if full_speed:
			client.verify_full_speed()
		else:
			client.verify_duty(duty=duty)

	try:
		verify()
	except BmcTransientReadError as exc:
		LOG.warning('%s; retrying readback once', exc)
		time.sleep(READ_RETRY_DELAY_SECONDS)
		verify()


def bmc_from_credential() -> BmcClient:
	directory = os.environ.get('CREDENTIALS_DIRECTORY')
	credential = Path(directory) / CREDENTIAL_NAME if directory else Path.home() / '.creds/kveikur-bmc'
	try:
		if credential.is_symlink():
			raise ValueError('credential is a symlink')
		data = json.loads(credential.read_text(encoding='utf-8'))
		username, password = data['username'], data['password']
		if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
			raise ValueError('invalid credential')
		return BmcClient(username=username, password=password)
	except (OSError, ValueError, KeyError, TypeError) as exc:
		raise BmcError('cannot load BMC credential') from exc


def read_profile(*, path: Path) -> str:
	try:
		name = path.read_text(encoding='utf-8').strip()
	except FileNotFoundError:
		return DEFAULT_PROFILE
	if name not in PROFILE_NAMES:
		raise ValueError('invalid saved profile')
	return name


def select_profile(*, path: Path, name: str) -> None:
	if name not in PROFILE_NAMES:
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


def read_gpus(*, root: Path, allow_empty: bool = False) -> List[dict]:
	selected_pci = selected_pci_ids()
	devices: Dict[str, dict] = {}
	try:
		entries = sorted(path for path in root.iterdir() if path.name.startswith('hwmon'))
		for path in entries:
			try:
				if (path / 'name').read_text(encoding='utf-8').strip() != 'amdgpu':
					continue
				device = path / 'device'
				if (device / 'vendor').read_text().strip() != GPU_VENDOR or (device / 'device').read_text().strip() != GPU_DEVICE:
					continue
				pci_id = device.resolve(strict=True).name
				if selected_pci is not None and pci_id not in selected_pci:
					continue
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
	expected_gpus = len(selected_pci) if selected_pci is not None else EXPECTED_GPUS
	if len(devices) != expected_gpus and not (allow_empty and not devices):
		raise SensorError(f'expected {expected_gpus} V620 GPUs, found {len(devices)}')
	return [devices[key] for key in sorted(devices)]


def selected_pci_ids() -> Optional[set[str]]:
	value = os.environ.get('AMD_FAN_PCI_IDS', '').strip()
	if not value:
		return None
	identifiers = {identifier.strip() for identifier in value.split(',') if identifier.strip()}
	if not identifiers:
		raise SensorError('AMD_FAN_PCI_IDS contains no valid PCI identifiers')
	return identifiers


def read_temperatures(*, root: Path, pci_root: Path) -> List[dict]:
	gpus = read_gpus(root=root, allow_empty=True)
	if not gpus:
		try:
			for device in pci_root.iterdir():
				if ((device / 'vendor').read_text().strip() == GPU_VENDOR and
						(device / 'device').read_text().strip() == GPU_DEVICE and (device / 'driver').is_symlink()):
					raise SensorError('driver-bound V620 without temperature readings')
		except OSError as exc:
			raise SensorError('cannot verify V620 driver state') from exc
	return gpus


def duty_for(*, profile: str, temperature_c: float) -> int:
	if profile == FULL_SPEED_PROFILE:
		return 100
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
	if not gpus:
		effective = FULL_SPEED_PROFILE if profile == FULL_SPEED_PROFILE else DEFAULT_PROFILE
		return {'profile': profile, 'effective_profile': effective, 'gpus': [],
			'hottest_c': None, 'control_c': None, 'proposed_duty_percent': duty_for(profile=effective, temperature_c=0),
			'control_enabled': False, 'sensor_state': 'no-driver-bound-gpus'}
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


def sample(*, path: Path, root: Path, previous_temperature_c: Optional[float] = None, pci_root: Path = PCI_ROOT) -> dict:
	try:
		return evaluate(profile=read_profile(path=path), gpus=read_temperatures(root=root, pci_root=pci_root), previous_temperature_c=previous_temperature_c)
	except (SensorError, OSError, ValueError) as exc:
		return {'control_enabled': False, 'error': str(exc), 'proposed_duty_percent': 100}


def notify(*, message: str) -> None:
	address = os.environ.get('NOTIFY_SOCKET')
	if not address:
		return
	if address.startswith('@'):
		address = '\0' + address[1:]
	with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
		sock.connect(address)
		sock.sendall(message.encode())


def write_status(*, path: Path, result: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temp = path.with_name(f'.status-{os.getpid()}')
	try:
		with temp.open('x', encoding='utf-8') as stream:
			json.dump(dict(result, updated_monotonic=time.monotonic()), stream)
			stream.write('\n')
		os.replace(temp, path)
	finally:
		if temp.exists():
			temp.unlink()


def read_status(*, path: Path) -> Optional[dict]:
	try:
		result = json.loads(path.read_text(encoding='utf-8'))
		age = time.monotonic() - float(result['updated_monotonic'])
		if age < 0 or age > 30:
			return None
		return result
	except (OSError, KeyError, TypeError, ValueError):
		return None


def run_monitor(*, path: Path, root: Path, status_path: Path, client: BmcClient, pci_root: Path = PCI_ROOT) -> int:
	stopping = False
	orderly_stop = False

	def stop(_signum: int, _frame: object) -> None:
		nonlocal stopping
		stopping = True

	signal.signal(signal.SIGTERM, stop)
	signal.signal(signal.SIGINT, stop)
	previous: Optional[float] = None
	last_duty: Optional[int] = None
	last_profile: Optional[str] = None
	telemetry_seen = False
	last_write = 0.0
	last_verified = 0.0
	readback_degraded = False
	need_login = True
	ready_sent = False
	outage_since: Optional[float] = None
	failures = 0
	write_uncertain = False

	def sample_adaptive(*, profile: str) -> dict:
		nonlocal telemetry_seen
		gpus = read_temperatures(root=root, pci_root=pci_root)
		if telemetry_seen and not gpus:
			raise SensorError('lost readings from both V620s after monitoring started')
		telemetry_seen = telemetry_seen or bool(gpus)
		return evaluate(profile=profile, gpus=gpus, previous_temperature_c=previous)

	try:
		while not stopping:
			notify(message='WATCHDOG=1')
			try:
				profile = read_profile(path=path)
				if need_login:
					client.login()
					mode = client.request(path='/api/fanctrl/mode')
					if not isinstance(mode, dict) or mode.get('FanMode') not in (0, FULL_SPEED_MODE, CUSTOM_MODE):
						raise BmcError('BMC fan mode is unavailable or unsupported')
					need_login = False
				if last_duty is not None and last_profile is not None:
					verify_running_setting(client=client, duty=last_duty, full_speed=last_profile == FULL_SPEED_PROFILE)
				if stopping:
					break
				if profile == FULL_SPEED_PROFILE:
					if last_profile != profile or readback_degraded:
						write_uncertain = True
						client.full_speed()
						write_uncertain = False
					previous, last_duty = None, 100
					result = {'profile': profile, 'proposed_duty_percent': 100}
				else:
					result = sample_adaptive(profile=profile)
					if stopping:
						break
					previous = result['control_c']
					duty = result['proposed_duty_percent']
					now = time.monotonic()
					if last_duty is None or profile != last_profile or readback_degraded or should_update_duty(profile=profile, duty=duty, last_duty=last_duty, elapsed=now - last_write):
						write_uncertain = True
						client.set_duty(duty=duty)
						write_uncertain = False
						last_duty, last_write = duty, now
				last_profile = profile
				last_verified = time.monotonic()
				if readback_degraded:
					LOG.info('BMC recovered; %s applied and verified at %s%%', profile, last_duty)
				readback_degraded, outage_since, failures = False, None, 0
				result.update(service_ready=True, control_enabled=True, verified_requested_duty_percent=last_duty,
					bmc_reachable=True, bmc_mode='full-speed' if profile == FULL_SPEED_PROFILE else 'customized')
				write_status(path=status_path, result=result)
			except BmcTransientError as exc:
				if stopping:
					break
				# Never claim a fallback was applied while the BMC is unreachable.
				# Keep checking GPU sensors, reconnect, and explicitly apply quiet on recovery.
				if read_profile(path=path) != DEFAULT_PROFILE:
					select_profile(path=path, name=DEFAULT_PROFILE)
				result = sample_adaptive(profile=DEFAULT_PROFILE)
				previous = result['control_c']
				now = time.monotonic()
				outage_since = now if outage_since is None else outage_since
				failures += 1
				if not readback_degraded or failures % 6 == 0:
					LOG.warning('%s; quiet recovery selected, BMC control unverified; retrying', exc)
				if now - outage_since >= BMC_OUTAGE_WARNING_SECONDS or (result['hottest_c'] is not None and result['hottest_c'] >= BMC_OUTAGE_WARNING_TEMP_C):
					LOG.critical('Cooling is unverified during BMC outage; verify airflow and avoid sustained GPU load')
				result.update(service_ready=True, control_enabled=False, readback_degraded=True,
					bmc_reachable=False, recovery_profile=DEFAULT_PROFILE, error=str(exc),
					last_verified_duty_percent=last_duty, last_verified_monotonic=last_verified or None,
					setting_uncertain=write_uncertain, bmc_outage_seconds=now - outage_since)
				if write_uncertain:
					# A PUT may have succeeded even if its reply/readback was lost.
					# Do not compare the next readback against a stale expected curve.
					last_duty, last_profile, write_uncertain = None, None, False
				readback_degraded, need_login = True, True
				write_status(path=status_path, result=result)
			if not ready_sent:
				notify(message='READY=1')
				ready_sent = True
			notify(message='WATCHDOG=1')
			if not stopping:
				time.sleep(INTERVAL_SECONDS)
		orderly_stop = True
		return 0
	except (BmcError, SensorError, OSError, ValueError) as exc:
		LOG.error('fan control stopped: %s', exc)
		try:
			write_status(path=status_path, result={'control_enabled': False, 'error': str(exc)})
		except OSError:
			LOG.error('could not write fan-control status')
		return 1
	finally:
		try:
			write_status(path=status_path, result={'control_enabled': False, 'error': 'fan controller stopped'})
		except OSError:
			LOG.error('could not mark fan control inactive')
		if not orderly_stop:
			try:
				client.full_speed()
				LOG.warning('BMC full-speed mode confirmed')
			except BmcError:
				try:
					client.login()
					client.full_speed()
					LOG.warning('BMC full-speed mode confirmed after reconnecting')
				except BmcError:
					LOG.critical('could not set BMC full-speed mode; verify cooling immediately')


def should_update_duty(*, profile: str, duty: int, last_duty: int, elapsed: float) -> bool:
	if duty == 100 > last_duty or duty >= last_duty + MIN_DUTY_CHANGE:
		return True
	# settle at the idle floor even if the final decrease is below the deadband
	floor = PROFILES[profile][0][1]
	return elapsed >= MAX_UPDATE_DELAY_SECONDS and (duty == floor < last_duty or duty <= last_duty - MIN_DUTY_CHANGE)


def guest_agent_responds() -> bool:
	try:
		result = subprocess.run(['/usr/sbin/qm', 'agent', '105', 'ping'], capture_output=True, timeout=7, check=False)
		return result.returncode == 0
	except (OSError, subprocess.TimeoutExpired):
		return False


def guest_fan_healthy() -> bool:
	# Evaluate freshness in the guest because host and guest monotonic clocks differ.
	probe = (
		'import json, subprocess, sys, time; '
		'v=json.load(open("/run/amd-fan/status.json")); '
		'age=time.monotonic()-v["updated_monotonic"]; '
		'sys.exit(0 if subprocess.run(["systemctl", "is-active", "--quiet", "amd-fan.service"]).returncode == 0 '
		'and v.get("control_enabled") is True and 0 <= age <= 20 else 1)'
	)
	try:
		result = subprocess.run(['/usr/sbin/qm', 'guest', 'exec', '105', '--timeout', '7', '--',
			'python3', '-c', probe], capture_output=True, timeout=10, check=False)
		response = json.loads(result.stdout)
		return (result.returncode == 0 and isinstance(response, dict) and
			response.get('exited') == 1 and response.get('exitcode') == 0)
	except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
		return False


class HostWatchdog:
	def __init__(self, *, client: BmcClient):
		self.client = client
		self.failures = 0
		self.logged_in = False

	def check(self, *, healthy: bool) -> None:
		if healthy:
			self.failures = 0
			return
		self.failures += 1
		if self.failures < HOST_FAILURE_LIMIT:
			return
		try:
			if not self.logged_in:
				self.client.login()
				self.logged_in = True
			mode = self.client.request(path='/api/fanctrl/mode')
			if not isinstance(mode, dict) or mode.get('FanMode') != FULL_SPEED_MODE:
				self.client.full_speed()
				LOG.warning('VM fan controller unhealthy; BMC full-speed mode confirmed')
		except BmcError:
			self.logged_in = False
			LOG.critical('VM fan controller unhealthy and BMC control unavailable; verify cooling immediately')


def run_host_watchdog(*, client: BmcClient) -> int:
	if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'kveikur':
		LOG.error('host watchdog must run as root on kveikur')
		return 1
	stopping = False

	def stop(_signum: int, _frame: object) -> None:
		nonlocal stopping
		stopping = True

	signal.signal(signal.SIGTERM, stop)
	signal.signal(signal.SIGINT, stop)
	watchdog = HostWatchdog(client=client)
	for attempt in range(3):
		try:
			client.login()
			mode = client.request(path='/api/fanctrl/mode')
			if not isinstance(mode, dict) or not isinstance(mode.get('FanMode'), int):
				raise BmcError('BMC fan mode unavailable')
			watchdog.logged_in = True
			break
		except BmcTransientError as exc:
			if attempt < 2:
				LOG.warning('host watchdog transient BMC error; retrying: %s', exc)
				time.sleep(2)
				continue
			LOG.critical('host watchdog could not authenticate to BMC: %s', exc)
			return 1
		except BmcError as exc:
			LOG.critical('host watchdog could not authenticate to BMC: %s', exc)
			return 1
	notify(message='READY=1')
	while not stopping:
		watchdog.check(healthy=guest_fan_healthy())
		notify(message='WATCHDOG=1')
		if not stopping:
			time.sleep(HOST_POLL_SECONDS)
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(description='control the Radeon GPU fan hub')
	parser.add_argument('command', choices=(*PROFILE_NAMES, 'status', 'monitor', 'host-watchdog', 'emergency'))
	args = parser.parse_args()
	path = PROFILE_PATH
	if args.command in PROFILE_NAMES:
		current = read_status(path=STATUS_PATH)
		if not current or not current.get('service_ready'):
			print('fan service is unavailable; profile was not changed', file=sys.stderr)
			return 1
		requested_at = time.monotonic()
		try:
			select_profile(path=path, name=args.command)
		except (OSError, ValueError) as exc:
			print(f'profile not saved: {exc}', file=sys.stderr)
			return 1
		deadline = time.monotonic() + 25
		while time.monotonic() < deadline:
			current = read_status(path=STATUS_PATH)
			if current and current.get('control_enabled') and not current.get('readback_degraded') and current.get('profile') == args.command and current['updated_monotonic'] >= requested_at:
				if current.get('sensor_state') == 'no-driver-bound-gpus':
					print(f"no driver-bound V620s; quiet fallback, BMC requested duty {current['verified_requested_duty_percent']}%")
				else:
					print(f"{args.command} active; BMC requested duty {current['verified_requested_duty_percent']}%")
				return 0
			time.sleep(1)
		print(f'{args.command} saved, but the service did not confirm application', file=sys.stderr)
		return 1
	root = Path('/sys/class/hwmon')
	if args.command == 'status':
		result = sample(path=path, root=root)
		current = read_status(path=STATUS_PATH)
		result['service'] = current or {'control_enabled': False, 'error': 'service status unavailable or stale'}
		result['control_enabled'] = bool(current and current.get('control_enabled'))
		print(json.dumps(result, indent=2))
		return 1 if 'error' in result or not result['control_enabled'] else 0
	logging.basicConfig(level=logging.INFO, format='%(message)s')
	try:
		client = bmc_from_credential()
		if args.command == 'emergency':
			client.login()
			client.full_speed()
			LOG.warning('BMC full-speed mode confirmed')
			return 0
		if args.command == 'host-watchdog':
			return run_host_watchdog(client=client)
		return run_monitor(path=path, root=root, status_path=STATUS_PATH, client=client)
	except BmcError as exc:
		LOG.error('%s', exc)
		return 1


if __name__ == '__main__':
	sys.exit(main())
