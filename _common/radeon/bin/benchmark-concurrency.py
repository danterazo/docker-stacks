#!/usr/bin/env python3
"""Temporarily enable four vLLM sequences, benchmark cohorts, restore deployment."""

import argparse
import concurrent.futures
import importlib.util
import json
import signal
import statistics
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


MODULE = Path(__file__).with_name('benchmark-powercaps.py')
spec = importlib.util.spec_from_file_location('powercaps', MODULE)
powercaps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(powercaps)
COMPOSE = Path('/docker/vllm/compose.yaml')
ENV_FILE = Path('/docker/vllm/.env')


def command(args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def deploy(override):
    print(command(['docker', 'compose', '--env-file', str(ENV_FILE), '-f', str(COMPOSE), '-f', str(override),
                   'up', '-d', '--no-deps', '--pull', 'never', 'vllm']), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--caps', type=int, nargs='+', default=[250, 220, 200, 180, 160, 140, 120])
    parser.add_argument('--clients', type=int, nargs='+', default=[1, 2, 4])
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--prompt-repeats', type=int, default=160)
    parser.add_argument('--output-tokens', type=int, default=256)
    parser.add_argument('--base-url', default='http://192.168.30.150:8000')
    parser.add_argument('--api-key-file', type=Path, default=Path('/docker/vllm/.secrets'))
    args = parser.parse_args()
    if args.rounds < 1 or any(c not in [1, 2, 4] for c in args.clients):
        parser.error('Use positive rounds and cohort sizes 1, 2, or 4')
    cards = powercaps.discover()
    originals = [powercaps.read_int(hwmon / 'power1_cap') for _, hwmon in cards]
    for cap in args.caps:
        for _, hwmon in cards:
            if not powercaps.read_int(hwmon / 'power1_cap_min') <= cap * 1000000 <= min(
                250000000, powercaps.read_int(hwmon / 'power1_cap_max')):
                parser.error(f'Unsupported cap {cap}')
    args.output.mkdir(parents=True, exist_ok=False)
    api_key = powercaps.load_api_key(args.api_key_file)
    current = json.loads(command(['docker', 'inspect', 'vllm']))[0]
    original_command = current['Config']['Cmd']
    new_command = original_command.copy()
    index = new_command.index('--max-num-seqs') + 1
    new_command[index] = '4'
    original_override = args.output / 'restore-command.json'
    benchmark_override = args.output / 'four-sequences.json'
    for path, value in [(original_override, original_command), (benchmark_override, new_command)]:
        path.write_text(json.dumps({'services': {'vllm': {'command': value}}}, indent=2) + '\n')
    metadata = {'original_command': original_command, 'benchmark_command': new_command,
                'clients': args.clients, 'caps_w': args.caps, 'rounds': args.rounds,
                'prompt_repeats': args.prompt_repeats, 'output_tokens': args.output_tokens,
                'original_caps_uw': originals, 'image_id': current['Image'],
                'note': 'Synchronized homogeneous cohorts, not mixed continuous arrivals.'}
    (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    results = []
    deployed = False
    try:
        powercaps.wait_ready(args.base_url, 300)
        deployed = True
        deploy(benchmark_override)
        print('Waiting for reloaded model (four sequences)', flush=True)
        powercaps.wait_ready(args.base_url, 1200)
        model_request = Request(args.base_url + '/v1/models',
                                headers={'Authorization': f'Bearer {api_key}'})
        with urlopen(model_request, timeout=10) as response:
            model = json.load(response)['data'][0]['id']
        metadata['model'] = model
        (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print('Warming up four concurrent sequences', flush=True)
        warm_cap = originals[0] // 1000000
        if len(set(originals)) != 1:
            raise RuntimeError('Warm-up requires matching original caps')
        warm_barrier = threading.Barrier(4)
        def warm(client):
            warm_barrier.wait(timeout=10)
            return powercaps.request(args.base_url, model, cards, warm_cap, 32, 64, 90,
                args.output / f'warmup-{client}.json', check_idle=False, api_key=api_key)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(warm, range(4)))
        for round_index in range(args.rounds):
            caps = args.caps if round_index % 2 == 0 else list(reversed(args.caps))
            for cap in caps:
                powercaps.set_caps(cards, [cap * 1000000] * len(cards))
                for clients in args.clients:
                    time.sleep(12)
                    before = powercaps.metrics(args.base_url)
                    if before['num_requests_running'] or before['num_requests_waiting']:
                        raise RuntimeError('Unexpected competing request before cohort')
                    barrier = threading.Barrier(clients)
                    started = time.monotonic()
                    def run(client):
                        barrier.wait(timeout=10)
                        return powercaps.request(args.base_url, model, cards, cap,
                            args.prompt_repeats, args.output_tokens, 90,
                            args.output / f'r{round_index+1}-{cap}w-c{clients}-{client}.json',
                            check_idle=False, api_key=api_key)
                    print(f'Round {round_index+1}, {cap} W, {clients} clients', flush=True)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
                        requests = list(pool.map(run, range(clients)))
                    elapsed = time.monotonic() - started
                    after = powercaps.metrics(args.base_url)
                    if after['prefix_cache_hits_total'] != before['prefix_cache_hits_total']:
                        raise RuntimeError('Unexpected prefix-cache hit in cohort')
                    result = {
                        'round': round_index + 1, 'cap_w': cap, 'clients': clients,
                        'elapsed_s': elapsed,
                        'aggregate_output_tokens_s': clients * args.output_tokens / elapsed,
                        'sum_decode_tokens_s': sum(r['decode_tokens_s'] for r in requests),
                        'mean_request_decode_tokens_s': statistics.mean(r['decode_tokens_s'] for r in requests),
                        'mean_ttft_s': statistics.mean(r['ttft_s'] for r in requests),
                        'max_ttft_s': max(r['ttft_s'] for r in requests),
                        'requests': requests,
                    }
                    results.append(result)
                    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
                    print(json.dumps({k: v for k, v in result.items() if k != 'requests'}), flush=True)
    finally:
        failures = []
        for card, value in zip(cards, originals, strict=True):
            try:
                powercaps.set_caps([card], [value])
            except Exception as exc:
                failures.append(str(exc))
        if deployed:
            print('Restoring original vLLM command', flush=True)
            deploy(original_override)
            powercaps.wait_ready(args.base_url, 1200)
        print(f'Restored original caps and deployment; cap failures={failures}', flush=True)
        if failures:
            raise RuntimeError('Cap restoration failed: ' + '; '.join(failures))


if __name__ == '__main__':
    main()
