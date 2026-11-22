#!/usr/bin/env python3
"""Test the cap sweep's reversible writes without touching real GPUs."""

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / 'bin/benchmark-powercaps.py'
spec = importlib.util.spec_from_file_location('benchmark_powercaps', MODULE)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class PowercapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp/opencode')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cards = []
        for index in range(2):
            hwmon = self.root / f'hwmon{index}'
            hwmon.mkdir()
            for name, value in [('power1_cap', 120000000),
                                ('power1_cap_min', 120000000),
                                ('power1_cap_max', 250000000)]:
                (hwmon / name).write_text(str(value) + '\n')
            self.cards.append((f'0000:0{index + 1}:00.0', hwmon))

    def values(self):
        return [benchmark.read_int(hwmon / 'power1_cap') for _, hwmon in self.cards]

    def test_apply_and_restore_distinct_caps(self):
        benchmark.set_caps(self.cards, [180000000, 200000000])
        self.assertEqual(self.values(), [180000000, 200000000])
        benchmark.set_caps(self.cards, [120000000, 120000000])
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_readback_mismatch_fails(self):
        with mock.patch.object(benchmark, 'read_int', return_value=120000000):
            with self.assertRaisesRegex(RuntimeError, 'readback'):
                benchmark.set_caps(self.cards, [180000000, 180000000])

    def run_main(self, side_effect, extra=()):
        response = io.BytesIO(b'{"data":[{"id":"test-model"}]}')
        args = ['benchmark-powercaps', '--output', str(self.root / 'results'),
                '--caps', '250', '180', '--rounds', '1', *extra]
        with mock.patch.object(sys, 'argv', args), \
                mock.patch.object(benchmark, 'discover', return_value=self.cards), \
                mock.patch.object(benchmark, 'urlopen', return_value=response), \
                mock.patch.object(benchmark, 'request', side_effect=side_effect), \
                mock.patch.object(benchmark.time, 'sleep'), \
                mock.patch.object(benchmark.signal, 'signal'), \
                mock.patch('builtins.print'):
            benchmark.main()

    def test_restore_after_thermal_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'thermal cutoff'):
            self.run_main([{}, RuntimeError('thermal cutoff')])
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_restore_after_interrupt(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_main([{}, KeyboardInterrupt()])
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_restore_after_success(self):
        self.run_main([{}, {'cap_w': 250}, {'cap_w': 180}])
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_reject_above_factory_limit_before_writes(self):
        with mock.patch.object(sys, 'argv', ['benchmark-powercaps', '--output',
                str(self.root / 'results'), '--caps', '260']), \
                mock.patch.object(benchmark, 'discover', return_value=self.cards), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                benchmark.main()
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_reject_unsafe_thermal_cutoff(self):
        with mock.patch.object(sys, 'argv', ['benchmark-powercaps', '--output',
                str(self.root / 'results'), '--cutoff-c', '100']), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                benchmark.main()
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_wait_requires_idle_server_and_healthy_fans(self):
        now = [0]
        server_calls = [0]
        def server(_base):
            server_calls[0] += 1
            return {'num_requests_running': 1 if now[0] < 6 else 0,
                    'num_requests_waiting': 0}
        def sleep(seconds):
            now[0] += seconds
        def status(_path):
            return '{"service_ready":true,"control_enabled":true,' + \
                   f'"updated_monotonic":{now[0]}' + '}'
        with mock.patch.object(benchmark, 'metrics', side_effect=server), \
                mock.patch.object(benchmark.time, 'monotonic', side_effect=lambda: now[0]), \
                mock.patch.object(benchmark.time, 'sleep', side_effect=sleep), \
                mock.patch.object(Path, 'read_text', status):
            benchmark.wait_ready('http://test', 60)
        self.assertEqual(now[0], 36)
        self.assertGreater(server_calls[0], 1)

    def test_wait_timeout_does_not_change_caps(self):
        with mock.patch.object(benchmark, 'metrics', side_effect=OSError('not ready')), \
                mock.patch.object(benchmark.time, 'monotonic', side_effect=[0, 0, 4]), \
                mock.patch.object(benchmark.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                benchmark.wait_ready('http://test', 3)
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_dynamic_cap_is_forwarded_and_originals_restored(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(kwargs.get('decode_cap'))
            if kwargs.get('decode_cap') is not None:
                benchmark.set_caps(self.cards, [kwargs['decode_cap'] * 1000000] * 2)
            return {}
        self.run_main(request, extra=['--decode-cap', '140'])
        self.assertEqual(calls, [None, 140, 140])
        self.assertEqual(self.values(), [120000000, 120000000])

    def test_reject_unsupported_dynamic_cap(self):
        with mock.patch.object(sys, 'argv', ['benchmark-powercaps', '--output',
                str(self.root / 'results'), '--decode-cap', '100']), \
                mock.patch.object(benchmark, 'discover', return_value=self.cards), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                benchmark.main()
        self.assertEqual(self.values(), [120000000, 120000000])


if __name__ == '__main__':
    unittest.main()
