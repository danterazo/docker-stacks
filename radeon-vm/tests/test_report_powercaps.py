#!/usr/bin/env python3
"""Check report units, reference comparisons, and GPU-energy integration."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / 'bin/report-powercaps.py'
spec = importlib.util.spec_from_file_location('report_powercaps', MODULE)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def result(cap=250, prefill=100, decode=20, total=10):
    return {'cap_w': cap, 'round': 1, 'prefill_tokens_s': prefill,
            'decode_tokens_s': decode, 'ttft_s': 2, 'total_s': total,
            'gpus': {pci: {'phases': {'prefill': {'mean_power_w': 30},
                                    'decode': {'mean_power_w': 20}},
                           'max_temperatures_c': {'junction': 70}}
                     for pci in ['0000:01:00.0', '0000:02:00.0']}}


class ReportTests(unittest.TestCase):
    def test_power_is_sum_of_boards_not_mean(self):
        self.assertEqual(report.phase_power(result(), 'decode'), 40)

    def test_comparisons_use_throughput_and_latency_correctly(self):
        table = report.fixed_table([result(), result(200, prefill=90, decode=18, total=11)])
        self.assertIn('-10.0%', table)
        self.assertIn('+10.0%', table)
        self.assertIn('0.5000', table)

    def test_energy_integrates_both_gpus_and_converts_to_wh(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp:
            directory = Path(temp)
            samples = [{'pci': pci, 'elapsed_s': timestamp, 'power_w': 20}
                       for pci in ['0000:01:00.0', '0000:02:00.0'] for timestamp in [0.1, 5, 9.5]]
            (directory / 'round-1-250w.sensors.json').write_text(json.dumps(samples))
            self.assertAlmostEqual(report.energy_wh(directory, result()), 400/3600)

    def test_incomplete_suite_is_not_reported_as_complete(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp:
            prefix = Path(temp) / 'suite'
            directory = Path(str(prefix) + '-short')
            directory.mkdir()
            (directory / 'metadata.json').write_text(json.dumps({'rounds': 2, 'caps_w': [250, 200]}))
            (directory / 'results.json').write_text(json.dumps([result()]))
            with self.assertRaisesRegex(RuntimeError, 'incomplete suite'):
                report.load(prefix, 'short')


if __name__ == '__main__':
    unittest.main()
