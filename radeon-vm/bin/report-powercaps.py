#!/usr/bin/env python3
"""Build comparable Markdown tables from a completed V620 benchmark suite."""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def mean(values):
    return statistics.mean(values)


def phase_power(result, phase):
    return sum(gpu['phases'][phase]['mean_power_w'] for gpu in result['gpus'].values())


def hot(result):
    return max(gpu['max_temperatures_c']['junction'] for gpu in result['gpus'].values())


def load(prefix, name):
    directory = Path(str(prefix) + '-' + name)
    metadata = json.loads((directory / 'metadata.json').read_text())
    results = json.loads((directory / 'results.json').read_text())
    expected = metadata['rounds'] * len(metadata['caps_w'])
    if name == 'concurrency':
        expected *= len(metadata['clients'])
    if len(results) != expected:
        raise RuntimeError(f'{name}: incomplete suite ({len(results)}/{expected})')
    return directory, metadata, results


def groups(results):
    grouped = defaultdict(list)
    for result in results:
        grouped[result['cap_w']].append(result)
    return grouped


def fixed_table(results):
    grouped = groups(results)
    baseline = grouped[250]
    prefill = mean(r['prefill_tokens_s'] for r in baseline)
    decode = mean(r['decode_tokens_s'] for r in baseline)
    elapsed = mean(r['total_s'] for r in baseline)
    rows = [
        '| Cap/card | Prefill tok/s | vs 250 W | Decode tok/s | vs 250 W | TTFT s | Total s | Latency change | Prefill GPU W¹ | Decode GPU W¹ | Decode tok/J¹ | Max hotspot °C |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for cap in sorted(grouped, reverse=True):
        runs = grouped[cap]
        p = mean(r['prefill_tokens_s'] for r in runs)
        d = mean(r['decode_tokens_s'] for r in runs)
        t = mean(r['total_s'] for r in runs)
        pw = mean(phase_power(r, 'prefill') for r in runs)
        dw = mean(phase_power(r, 'decode') for r in runs)
        rows.append(f'| {cap} W | {p:.1f} | {100*(p/prefill-1):+.1f}% | {d:.2f} | '
                    f'{100*(d/decode-1):+.1f}% | {mean(r["ttft_s"] for r in runs):.2f} | '
                    f'{t:.2f} | {100*(t/elapsed-1):+.1f}% | {pw:.0f} | {dw:.0f} | '
                    f'{d/dw:.4f} | {max(hot(r) for r in runs):.0f} |')
    return '\n'.join(rows)


def energy_wh(directory, result):
    path = directory / f'round-{result["round"]}-{result["cap_w"]}w.sensors.json'
    samples = json.loads(path.read_text())
    total = 0
    for pci in result['gpus']:
        points = sorted((s['elapsed_s'], s['power_w']) for s in samples
                        if s['pci'] == pci and 0 <= s['elapsed_s'] <= result['total_s'])
        if not points:
            raise RuntimeError('No energy samples')
        points = [(0, points[0][1]), *points, (result['total_s'], points[-1][1])]
        total += sum((right[0]-left[0])*(left[1]+right[1])/2
                     for left, right in zip(points, points[1:]))
    return total / 3600


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    suite = {name: load(args.prefix, name) for name in [
        'short', 'long', 'dynamic-160', 'dynamic-140', 'dynamic-120',
        'dynamic-baseline', 'concurrency',
    ]}
    metadata = suite['short'][1]
    rows = [
        '# V620 Power-Cap Measurements — 2026-11-22', '',
        f'Model: `{metadata["model"]}`. Two V620s, tensor parallelism 2. '
        'Two measurements per configuration, reverse cap order on the second pass. '
        'Values are means; hottest temperatures are maxima across both cards/passes.', '',
        'These are synthetic uncached, text-completion workloads, not a model-quality '
        'or tool-calling correctness test. Fan control remained adaptive. '
        'No wall-power meter was available. Differences below about 1–2% may be noise.', '',
    ]
    for name, heading in [('short', 'Short prompt'), ('long', 'Long prompt')]:
        directory, info, results = suite[name]
        rows += [f'## {heading}', '',
                 f'Prompt tokens: {min(r["prompt_tokens"] for r in results)}–'
                 f'{max(r["prompt_tokens"] for r in results)}; '
                 f'output: {info["output_tokens"]} tokens. '
                 'Prefill tok/s is prompt tokens / TTFT, including request overhead '
                 'and the first decode step.', '', fixed_table(results), '']
    rows += ['¹ GPU watts and tokens/J cover **both installed cards combined**, not '
             'the whole host. Phase-averaged power includes transition samples. '
             'A higher cap does not imply that much power is consumed during decode.', '',
             '## Dynamic capping versus fixed caps', '',
             'Same approximately 15.4K-token prompt and 512-token output. '
             'Switch after first streamed output text; switching time covers '
             'both cap writes and readback.', '',
             '| Prefill → decode cap | Prefill tok/s | Decode tok/s | Decode change² | TTFT s | Total s | Total change² | Decode GPU W | GPU energy Wh | Energy change² | Switch ms | Hotspot °C |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    baseline_directory, _, baseline_results = suite['dynamic-baseline']
    baselines = groups(baseline_results)
    for cap in sorted(baselines, reverse=True):
        runs = baselines[cap]
        rows.append(f'| {cap} → {cap} W | {mean(r["prefill_tokens_s"] for r in runs):.1f} | '
                    f'{mean(r["decode_tokens_s"] for r in runs):.2f} | — | '
                    f'{mean(r["ttft_s"] for r in runs):.2f} | {mean(r["total_s"] for r in runs):.2f} | — | '
                    f'{mean(phase_power(r,"decode") for r in runs):.0f} | '
                    f'{mean(energy_wh(baseline_directory,r) for r in runs):.3f} | — | — | '
                    f'{max(hot(r) for r in runs):.0f} |')
    for name in ['dynamic-160', 'dynamic-140', 'dynamic-120']:
        directory, _, results = suite[name]
        for cap, runs in sorted(groups(results).items(), reverse=True):
            baseline = baselines[cap]
            d = mean(r['decode_tokens_s'] for r in runs)
            t = mean(r['total_s'] for r in runs)
            e = mean(energy_wh(directory,r) for r in runs)
            bd = mean(r['decode_tokens_s'] for r in baseline)
            bt = mean(r['total_s'] for r in baseline)
            be = mean(energy_wh(baseline_directory,r) for r in baseline)
            rows.append(f'| {cap} → {runs[0]["decode_cap_w"]} W | '
                        f'{mean(r["prefill_tokens_s"] for r in runs):.1f} | {d:.2f} | '
                        f'{100*(d/bd-1):+.1f}% | {mean(r["ttft_s"] for r in runs):.2f} | '
                        f'{t:.2f} | {100*(t/bt-1):+.1f}% | '
                        f'{mean(phase_power(r,"decode") for r in runs):.0f} | {e:.3f} | '
                        f'{100*(e/be-1):+.1f}% | '
                        f'{mean(r["cap_switch_ms"] for r in runs):.2f} | {max(hot(r) for r in runs):.0f} |')
    rows += ['', '² Compared with the fixed cap matching the prefill cap. '
             'Energy is trapezoidal integration of half-second GPU power samples, '
             'with endpoint estimates; excludes CPU, fans, and PSU losses.', '',
             '## Concurrent agents', '',
             'vLLM temporarily allowed four sequences. Cohorts contain synchronized '
             'uncached prompts of about 3.9K tokens and 256 output tokens per client. '
             'Per-agent decode rates exclude prefill; aggregate output tok/s includes '
             'the entire cohort duration. Compare caps within the same client count.', '']
    concurrency = suite['concurrency'][2]
    for clients in [1, 2, 4]:
        grouped = groups([r for r in concurrency if r['clients'] == clients])
        base = mean(r['aggregate_output_tokens_s'] for r in grouped[250])
        rows += [f'### {clients} concurrent client(s)', '',
                 '| Cap/card | Per-agent decode tok/s | Sum decode tok/s³ | Aggregate output tok/s | vs 250 W | Mean TTFT s | Worst TTFT s | Decode GPU W⁴ | Hotspot °C |',
                 '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for cap, runs in sorted(grouped.items(), reverse=True):
            rate = mean(r['aggregate_output_tokens_s'] for r in runs)
            requests = [request for r in runs for request in r['requests']]
            rows.append(f'| {cap} W | {mean(r["mean_request_decode_tokens_s"] for r in runs):.2f} | '
                        f'{mean(r["sum_decode_tokens_s"] for r in runs):.2f} | {rate:.2f} | '
                        f'{100*(rate/base-1):+.1f}% | {mean(r["mean_ttft_s"] for r in runs):.2f} | '
                        f'{max(r["max_ttft_s"] for r in runs):.2f} | '
                        f'{mean(phase_power(r,"decode") for r in requests):.0f} | '
                        f'{max(hot(r) for r in requests):.0f} |')
        rows += ['']
    rows += ['³ Sum of overlapping per-request decode rates, not a separately timed '
             'global steady-state window. ⁴ GPU power averaged across request decode '
             'windows; not multiplied by the number of clients.', '',
             '## Four-card PSU budget', '',
             '| Cap/card | Two-card nominal GPU cap | Four-card nominal GPU cap | Remaining from 1600 W DC rating |',
             '|---:|---:|---:|---:|']
    for cap in [250, 220, 210, 200, 180, 160, 140, 120]:
        rows.append(f'| {cap} W | {2*cap} W | {4*cap} W | {1600-4*cap} W |')
    rows += ['', 'Remaining capacity must cover CPU, motherboard, storage, fans, and '
             'transient margin. Runtime caps are not a substitute for stock-power '
             'sizing, correct cabling, or four-card cooling validation.', '',
             '## Raw data', '', f'Suite prefix: `{args.prefix}`. '
             'Each directory contains metadata, request summaries, and sensor samples. '
             'The concurrency directory includes original and temporary command overrides.', '']
    args.output.write_text('\n'.join(rows))
    print(args.output)


if __name__ == '__main__':
    main()
