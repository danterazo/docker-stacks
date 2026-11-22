#!/usr/bin/env python3
"""Verify temporary concurrency deployment and cap restoration using fakes."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / 'bin/benchmark-concurrency.py'
spec = importlib.util.spec_from_file_location('benchmark_concurrency', MODULE)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cards = []
        for index in range(2):
            hwmon = self.root / f'hwmon{index}'
            hwmon.mkdir()
            for name, value in [('power1_cap', 120000000),
                                ('power1_cap_min', 120000000),
                                ('power1_cap_max', 250000000)]:
                (hwmon / name).write_text(str(value))
            self.cards.append((f'0000:0{index+1}:00.0', hwmon))

    def run_main(self, request_effect):
        deployed = []
        def deploy(path):
            deployed.append(json.loads(path.read_text())['services']['vllm']['command'])
        inspect = json.dumps([{'Config': {'Cmd': ['serve', '/model', '--max-num-seqs', '1']},
                               'Image': 'test-image'}])
        metrics = {'num_requests_running': 0, 'num_requests_waiting': 0, 'prefix_cache_hits_total': 0}
        args = ['benchmark-concurrency', '--output', str(self.root / 'results'),
                '--caps', '180', '--clients', '1', '--rounds', '1']
        self.deployed = deployed
        with mock.patch.object(sys, 'argv', args), \
                mock.patch.object(benchmark.powercaps, 'discover', return_value=self.cards), \
                mock.patch.object(benchmark, 'command', return_value=inspect), \
                mock.patch.object(benchmark, 'deploy', side_effect=deploy), \
                mock.patch.object(benchmark, 'urlopen', return_value=io.BytesIO(b'{"data":[{"id":"test"}]}')), \
                mock.patch.object(benchmark.powercaps, 'wait_ready'), \
                mock.patch.object(benchmark.powercaps, 'metrics', return_value=metrics), \
                mock.patch.object(benchmark.powercaps, 'request', side_effect=request_effect), \
                mock.patch.object(benchmark.time, 'sleep'), \
                mock.patch.object(benchmark.signal, 'signal'), \
                mock.patch('builtins.print'):
            benchmark.main()

    def assert_restored(self):
        self.assertEqual([benchmark.powercaps.read_int(hwmon / 'power1_cap')
                          for _, hwmon in self.cards], [120000000, 120000000])
        self.assertEqual(self.deployed[0][-1], '4')
        self.assertEqual(self.deployed[-1][-1], '1')

    def test_deploy_uses_vm_compose_and_vm_environment(self):
        override = self.root / 'override.json'
        with mock.patch.object(benchmark, 'command', return_value='ok') as command, \
                mock.patch('builtins.print'):
            benchmark.deploy(override)
        command.assert_called_once_with([
            'docker', 'compose', '--env-file', '/docker/vllm/.env.vm.local',
            '-f', '/docker/vllm/compose.vm.yaml', '-f', str(override),
            'up', '-d', '--no-deps', '--pull', 'never', 'vllm',
        ])

    def test_restore_after_success(self):
        self.run_main(lambda *a, **k: {'decode_tokens_s': 25, 'ttft_s': 5})
        self.assert_restored()

    def test_restore_after_request_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'thermal cutoff'):
            self.run_main(RuntimeError('thermal cutoff'))
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
