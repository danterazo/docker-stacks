#!/usr/bin/env python3
"""Reversible, single-request vLLM power-cap sweep with GPU safety monitoring."""

import argparse
import http.client
import json
import re
import signal
import socket
import statistics
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def discover():
    cards = []
    for hwmon in sorted(Path('/sys/class/hwmon').glob('hwmon*')):
        device = hwmon / 'device'
        if not device.exists():
            continue
        ids = ['vendor', 'device', 'subsystem_vendor', 'subsystem_device']
        if [ (device / name).read_text().strip() for name in ids ] != [
            '0x1002', '0x73a1', '0x1002', '0x0e34'
        ]:
            continue
        cards.append((device.resolve().name, hwmon))
    if not cards:
        raise RuntimeError('No V620 power controls found')
    return cards


def read_int(path):
    return int(path.read_text().strip())


def load_api_key(path, name='VLLM_API_KEY_KVEIKUR'):
    values = []
    for line in Path(path).read_text().splitlines():
        key, separator, value = line.partition(':')
        if separator and key.strip() == name:
            values.append(value.strip())
    if len(values) != 1 or not re.fullmatch(r'[0-9a-f]{64}', values[0]):
        raise RuntimeError(f'Expected one 64-character hexadecimal {name} entry in {path}')
    return values[0]


def set_caps(cards, values):
    for (_, hwmon), value in zip(cards, values, strict=True):
        path = hwmon / 'power1_cap'
        path.write_text(str(value) + '\n')
        if read_int(path) != value:
            raise RuntimeError(f'Cap readback failed: {path}')


def metrics(base):
    with urlopen(base + '/metrics', timeout=10) as response:
        text = response.read().decode()
    result = {}
    for name in ['num_requests_running', 'num_requests_waiting', 'prefix_cache_hits_total']:
        result[name] = sum(float(value) for value in re.findall(
            rf'^vllm:{name}\{{[^\n]*\}} ([0-9.e+\-]+)$', text, re.M))
    return result


def wait_ready(base, timeout):
    deadline = time.monotonic() + timeout
    idle_since = None
    while True:
        now = time.monotonic()
        try:
            server = metrics(base)
            fan = json.loads(Path('/run/amd-fan/status.json').read_text())
            ready = (not server['num_requests_running'] and not server['num_requests_waiting']
                     and fan.get('service_ready') and fan.get('control_enabled')
                     and now - fan['updated_monotonic'] < 20)
        except Exception:
            ready = False
        if ready:
            idle_since = now if idle_since is None else idle_since
            if now - idle_since >= 30:
                return
        else:
            idle_since = None
        if now >= deadline:
            raise RuntimeError('Timed out waiting for idle server and healthy fan control')
        time.sleep(3)


def request(base, model, cards, cap, repeats, output_tokens, cutoff, destination,
            decode_cap=None, check_idle=True, api_key=None):
    before = metrics(base) if check_idle else None
    if before and (before['num_requests_running'] or before['num_requests_waiting']):
        raise RuntimeError('Server has another active/queued request; refusing to benchmark')
    # Unique text at the very start avoids cached prefixes without flushing other users' caches.
    prompt = f'Benchmark nonce {uuid.uuid4().hex}.\n' + (
        'The river flows past the village. Engineers measure power, temperature, '
        'latency, and throughput under a repeatable workload.\n' * repeats
    ) + '\nWrite a detailed explanation of efficient inference, continuing until the output limit.\n'
    body = json.dumps({
        'model': model, 'prompt': prompt, 'max_tokens': output_tokens,
        'temperature': 0, 'seed': 42, 'ignore_eos': True,
        'stream': True, 'stream_options': {'include_usage': True},
    })
    url = urlsplit(base)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=180)
    stop = threading.Event()
    errors = []
    samples = []
    started = time.monotonic()
    first = None
    last = None
    usage = None
    chunks = 0
    cap_lock = threading.Lock()
    expected_cap = [cap]
    switch_ms = None

    def monitor():
        while not stop.is_set():
            try:
                now = time.monotonic()
                fan = json.loads(Path('/run/amd-fan/status.json').read_text())
                if not fan.get('service_ready') or not fan.get('control_enabled'):
                    raise RuntimeError('Fan control not ready')
                if now - fan['updated_monotonic'] > 35:
                    raise RuntimeError('Fan control status stale')
                for pci, hwmon in cards:
                    temperatures = {
                        label.read_text().strip(): read_int(label.with_name(
                            label.name.replace('_label', '_input'))) / 1000
                        for label in hwmon.glob('temp*_label')
                    }
                    if not {'edge', 'junction', 'mem'} <= temperatures.keys():
                        raise RuntimeError('Required temperature sensor missing')
                    if max(temperatures.values()) >= cutoff:
                        raise RuntimeError(f'{pci}: thermal cutoff {temperatures}')
                    with cap_lock:
                        if read_int(hwmon / 'power1_cap') != expected_cap[0] * 1000000:
                            raise RuntimeError(f'{pci}: cap changed during benchmark')
                        sampled_cap = expected_cap[0]
                    sample = {
                        'elapsed_s': now - started, 'pci': pci,
                        'power_w': read_int(hwmon / 'power1_average') / 1000000,
                        'temperatures_c': temperatures,
                        'gpu_busy_percent': read_int(hwmon / 'device/gpu_busy_percent'),
                        'core_mhz': read_int(hwmon / 'freq1_input') / 1000000,
                        'memory_mhz': read_int(hwmon / 'freq2_input') / 1000000,
                        'fan_duty_percent': fan.get('verified_requested_duty_percent'),
                        'fan_profile': fan.get('profile'),
                        'cap_w': sampled_cap,
                    }
                    samples.append(sample)
            except Exception as exc:
                errors.append(str(exc))
                stop.set()
                if connection.sock:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return
            stop.wait(0.5)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        if errors:
            raise RuntimeError(errors[0])
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        connection.request('POST', '/v1/completions', body=body, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f'Inference HTTP {response.status}: {response.read()[:500]!r}')
        while True:
            line = response.readline()
            if errors:
                raise RuntimeError(errors[0])
            if not line:
                break
            if not line.startswith(b'data: '):
                continue
            data = line[6:].strip()
            if data == b'[DONE]':
                break
            event = json.loads(data)
            if 'error' in event:
                raise RuntimeError(str(event['error']))
            if event.get('usage'):
                usage = event['usage']
            for choice in event.get('choices', []):
                if choice.get('text'):
                    now = time.monotonic()
                    if first is None:
                        first = now
                        if decode_cap is not None:
                            switch_started = time.monotonic()
                            with cap_lock:
                                set_caps(cards, [decode_cap * 1000000] * len(cards))
                                expected_cap[0] = decode_cap
                            switch_ms = (time.monotonic() - switch_started) * 1000
                    last = now
                    chunks += 1
        if not usage or usage['completion_tokens'] != output_tokens or first is None or last <= first:
            raise RuntimeError(f'Incomplete inference: usage={usage}, chunks={chunks}')
    finally:
        stop.set()
        connection.close()
        thread.join(timeout=3)
        destination.with_suffix('.sensors.json').write_text(json.dumps(samples, indent=2) + '\n')
    if errors:
        raise RuntimeError(errors[0])
    after = metrics(base) if check_idle else None
    if after and after['prefix_cache_hits_total'] != before['prefix_cache_hits_total']:
        raise RuntimeError('Prefix cache hit detected; run invalid')
    ttft = first - started
    result = {
        'cap_w': cap, 'prompt_tokens': usage['prompt_tokens'], 'output_tokens': output_tokens,
        'ttft_s': ttft, 'prefill_tokens_s': usage['prompt_tokens'] / ttft,
        'decode_tokens_s': (output_tokens - 1) / (last - first),
        'total_s': last - started, 'stream_chunks': chunks, 'prefix_cache_hits': 0,
        'decode_cap_w': decode_cap if decode_cap is not None else cap,
        'cap_switch_ms': switch_ms,
        'gpus': {},
    }
    for pci, _ in cards:
        per_card = [s for s in samples if s['pci'] == pci]
        phases = {}
        for phase in ['prefill', 'decode']:
            subset = [s for s in per_card if (s['elapsed_s'] < ttft) == (phase == 'prefill')]
            if subset:
                phases[phase] = {
                    'mean_power_w': statistics.mean(s['power_w'] for s in subset),
                    'max_power_w': max(s['power_w'] for s in subset),
                    'mean_core_mhz': statistics.mean(s['core_mhz'] for s in subset),
                    'mean_busy_percent': statistics.mean(s['gpu_busy_percent'] for s in subset),
                }
        result['gpus'][pci] = {
            'phases': phases,
            'max_temperatures_c': {name: max(s['temperatures_c'][name] for s in per_card)
                                   for name in ['edge', 'junction', 'mem']},
        }
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caps', nargs='+', type=int, default=[250, 220, 200, 180, 160, 140, 120])
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--prompt-repeats', type=int, default=160)
    parser.add_argument('--output-tokens', type=int, default=192)
    parser.add_argument('--cutoff-c', type=float, default=90)
    parser.add_argument('--base-url', default='http://192.168.30.150:8000')
    parser.add_argument('--api-key-file', type=Path, default=Path('/docker/vllm/.secrets'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--decode-cap', type=int,
                        help='Switch both GPUs to this cap after the first output token')
    parser.add_argument('--wait-ready', type=int, default=0,
                        help='Wait this many seconds for 30s of idle server and healthy fan control')
    args = parser.parse_args()
    if args.rounds < 1 or args.prompt_repeats < 1 or args.output_tokens < 2 or not 0 < args.cutoff_c <= 90:
        parser.error('Invalid workload or unsafe thermal cutoff')
    cards = discover()
    originals = [read_int(hwmon / 'power1_cap') for _, hwmon in cards]
    for cap in args.caps + ([] if args.decode_cap is None else [args.decode_cap]):
        for _, hwmon in cards:
            if not read_int(hwmon / 'power1_cap_min') <= cap * 1000000 <= min(
                250000000, read_int(hwmon / 'power1_cap_max')
            ):
                parser.error(f'{cap} W outside supported/factory range')
    args.output.mkdir(parents=True, exist_ok=False)
    api_key = load_api_key(args.api_key_file)
    if args.wait_ready:
        print('Waiting for idle server and healthy fan control', flush=True)
        wait_ready(args.base_url, args.wait_ready)
    model_request = Request(args.base_url + '/v1/models',
                            headers={'Authorization': f'Bearer {api_key}'})
    with urlopen(model_request, timeout=10) as response:
        model = json.load(response)['data'][0]['id']
    metadata = {
        'model': model, 'cards': [pci for pci, _ in cards], 'original_caps_uw': originals,
        'caps_w': args.caps, 'rounds': args.rounds, 'prompt_repeats': args.prompt_repeats,
        'output_tokens': args.output_tokens, 'cutoff_c': args.cutoff_c,
        'decode_cap_w': args.decode_cap,
        'note': 'Single-sequence TP2 workload; restored original caps on exit. No four-card validation.',
    }
    (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    results = []
    try:
        print('Warm-up at starting cap', flush=True)
        if len(set(originals)) != 1:
            raise RuntimeError('Warm-up requires matching initial caps')
        request(args.base_url, model, cards, originals[0] // 1000000, 32, 64,
                args.cutoff_c, args.output / 'warmup.json', api_key=api_key)
        for round_index in range(args.rounds):
            # Reverse the sweep in round 2 to expose temperature/time ordering bias.
            caps = args.caps if round_index % 2 == 0 else list(reversed(args.caps))
            for cap in caps:
                set_caps(cards, [cap * 1000000] * len(cards))
                # vLLM engine gauges refresh asynchronously; allow the prior request to clear.
                time.sleep(12)
                print(f'Round {round_index + 1}, cap {cap} W', flush=True)
                result = request(args.base_url, model, cards, cap, args.prompt_repeats,
                                 args.output_tokens, args.cutoff_c,
                                 args.output / f'round-{round_index + 1}-{cap}w.json',
                                 decode_cap=args.decode_cap, api_key=api_key)
                result['round'] = round_index + 1
                results.append(result)
                (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    finally:
        failures = []
        for card, value in zip(cards, originals, strict=True):
            try:
                set_caps([card], [value])
            except Exception as exc:
                failures.append(str(exc))
        print(f'Restored starting caps; failures={failures}', flush=True)
        if failures:
            raise RuntimeError('Could not restore every cap: ' + '; '.join(failures))


if __name__ == '__main__':
    main()
