#!/usr/bin/env python3
"""Validate Radeon sparse profiles and VM stack selection without running jobs."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SparseProfileTests(unittest.TestCase):
    def run_profile(self, hostname, existing):
        source = (ROOT / 'bootstrap.sh').read_text()
        profiles = source.split(": 'MULTI-TENANT HOSTS'", 1)[1].split(": 'SYSTEM CONFIG'", 1)[0]
        block = source.split('# host-specific sparse profiles', 1)[1].split('# move to app dir', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            sparse = Path(temp) / 'existing'
            sparse.write_text('\n'.join(existing) + '\n')
            script = '''
HOST_NAME="$TEST_HOST"
HOME_DIR="$TEST_ROOT"
REPO_CREATED=0
''' + profiles + '''
dante_git() {
    case "$3 $4 $5" in
        'config --get core.sparseCheckout') echo true ;;
        'config --get core.sparseCheckoutCone') echo false ;;
        'rev-parse --git-path info/sparse-checkout') echo "$TEST_SPARSE" ;;
        'sparse-checkout set --no-cone') shift 5; printf '%s\\n' "$@" ;;
        *) echo "unexpected dante_git call: $*" >&2; return 1 ;;
    esac
}
''' + block
            env = dict(os.environ, TEST_HOST=hostname, TEST_ROOT=temp, TEST_SPARSE=str(sparse))
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True, check=True)
            return result.stdout.splitlines()

    def test_vm_profile_includes_split_stacks_and_shared_helpers(self):
        patterns = self.run_profile('radeon-vm', ['/radeon-vm/', '!/_common/radeon/'])
        self.assertIn('/vllm/', patterns)
        self.assertIn('/llama-cpp/', patterns)
        self.assertIn('/_common/', patterns)
        self.assertIn('/radeon-vm/', patterns)
        self.assertNotIn('!/_common/radeon/', patterns)

    def test_other_hosts_keep_radeon_exclusion(self):
        patterns = self.run_profile('caddy', [])
        self.assertIn('/caddy/', patterns)
        self.assertIn('!/_common/radeon/', patterns)

    def test_radeon_lxcs_include_shared_helpers(self):
        for hostname in ('vllm', 'llama-cpp'):
            with self.subTest(hostname=hostname):
                patterns = self.run_profile(hostname, ['!/_common/radeon/'])
                self.assertIn('/' + hostname + '/', patterns)
                self.assertNotIn('!/_common/radeon/', patterns)


class VmStackSelectionTests(unittest.TestCase):
    def run_dpull(self, active, include_env=True, selected=None):
        source = (ROOT / '_common/functions.sh').read_text()
        function = source.split('dpull() {', 1)[1].split('\n# bootstrap, then pull Git', 1)[0]
        function = 'dpull() {' + function
        function = function.replace('local root_dir="/docker"', 'local root_dir="$TEST_ROOT"', 1)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.git').mkdir()
            for name in ('vllm', 'llama-cpp'):
                stack = root / name
                stack.mkdir()
                (stack / 'compose.yaml').write_text('services: {}\n')
                (stack / 'compose.vm.yaml').write_text('services: {}\n')
                if include_env:
                    (stack / '.env.vm.local').write_text('TEST=1\n')
            log = root / 'calls'
            script = '''
HOSTNAME=radeon-vm
git() {
    if [[ "$1 $2" == 'branch --show-current' ]]; then echo main; fi
    return 0
}
docker() {
    printf '%s\\n' "$*" >> "$TEST_LOG"
    if [[ "$1" == ps && "$*" == *"project=$TEST_ACTIVE"* && -n "$TEST_ACTIVE" ]]; then echo container-id; fi
    return 0
}
''' + function + '\ndpull\n'
            env = dict(os.environ, TEST_ROOT=temp, TEST_LOG=str(log), TEST_ACTIVE=active)
            if selected is not None:
                env['DPULL_VM_STACKS'] = selected
            else:
                env.pop('DPULL_VM_STACKS', None)
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_uses_vm_variant_only_for_running_stack(self):
        result, calls = self.run_dpull('vllm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('label=com.docker.compose.project=vllm' in call for call in calls))
        self.assertTrue(any('label=com.docker.compose.project=llama-cpp' in call for call in calls))
        compose = [call for call in calls if call.startswith('compose ')]
        self.assertEqual(len(compose), 3)
        self.assertTrue(all('--env-file .env.vm.local -f compose.vm.yaml' in call for call in compose))

    def test_inactive_vm_stacks_are_not_started(self):
        result, calls = self.run_dpull('')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith('compose ') for call in calls))

    def test_deep_deploy_restores_only_preselected_vm_stack(self):
        result, calls = self.run_dpull('', selected='vllm')
        self.assertEqual(result.returncode, 0, result.stderr)
        compose = [call for call in calls if call.startswith('compose ')]
        self.assertEqual(len(compose), 3)
        self.assertTrue(all('--env-file .env.vm.local -f compose.vm.yaml' in call for call in compose))
        self.assertFalse(any(call.startswith('ps ') for call in calls))

    def test_empty_deep_deploy_selection_stays_stopped(self):
        result, calls = self.run_dpull('', selected='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith('compose ') for call in calls))

    def test_missing_vm_env_stops_before_compose(self):
        result, calls = self.run_dpull('vllm', include_env=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call.startswith('compose ') for call in calls))


class DeepDeployTests(unittest.TestCase):
    def test_vm_teardown_preserves_only_active_stack_selection(self):
        doc = (ROOT / '.github/skills/deploy-deep/SKILL.md').read_text()
        code = doc.split('Aliases do not expand noninteractively', 1)[1].split('```bash\n', 1)[1].split('\n```', 1)[0]
        code = code.replace('cd /docker\n', 'cd "$TEST_ROOT"\n', 1)
        code = code.replace('source /docker/_common/functions.sh', 'source "$TEST_HELPERS"', 1)
        code = code.replace('for app_dir in /docker/*/;', 'for app_dir in "$TEST_ROOT"/*/;', 1)
        code = code.replace('== /docker/vllm', '== "$TEST_ROOT/vllm"')
        code = code.replace('== /docker/llama-cpp', '== "$TEST_ROOT/llama-cpp"')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('vllm', 'llama-cpp'):
                stack = root / name
                stack.mkdir()
                for file in ('compose.yaml', 'compose.vm.yaml', '.env.vm.local'):
                    (stack / file).write_text('fixture\n')
            log = root / 'calls'
            helper = root / 'helpers.sh'
            helper.write_text('dpull() { printf "dpull=%s\\n" "$DPULL_VM_STACKS" >> "$TEST_LOG"; }\n')
            setup = """
HOSTNAME=radeon-vm
docker() {
    printf '%s\\n' "$*" >> "$TEST_LOG"
    if [[ "$1" == ps && "$*" == *project=vllm* ]]; then echo container-id; fi
    return 0
}
"""
            env = dict(os.environ, TEST_ROOT=temp, TEST_LOG=str(log), TEST_HELPERS=str(helper))
            result = subprocess.run(['bash', '-c', setup + code], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            downs = [call for call in calls if call.startswith('compose ')]
            self.assertEqual(len(downs), 1)
            self.assertIn('--env-file .env.vm.local -f compose.vm.yaml down -v', downs[0])
            self.assertIn('dpull=vllm', calls)


class FanUnitGuardTests(unittest.TestCase):
    def test_controller_units_refuse_to_start_while_peer_is_active(self):
        units = {
            'amd-fan-host.service': 'amd-fan-watchdog.service',
            'amd-fan-watchdog.service': 'amd-fan-host.service',
        }
        for name, peer in units.items():
            with self.subTest(unit=name):
                text = (ROOT / '_common/radeon/systemd' / name).read_text()
                guard = f"ExecStartPre=/bin/sh -c '! /usr/bin/systemctl is-active --quiet {peer}'"
                self.assertEqual(text.count(guard), 1)
                self.assertLess(text.index(guard), text.index('ExecStart='))
                self.assertIn('ExecStopPost=', text)
                self.assertIn('ExecStart=/usr/bin/flock --nonblock --no-fork /run/amd-fan-control.lock ', text)
                command = f'! status_stub is-active --quiet {peer}'
                for peer_status, expected in ((0, 1), (3, 0)):
                    script = f'status_stub() {{ return {peer_status}; }}\n{command}'
                    result = subprocess.run(['/bin/sh', '-c', script], capture_output=True)
                    self.assertEqual(result.returncode, expected)


    def test_no_fork_lock_keeps_main_pid_and_excludes_peer(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = str(Path(temp) / 'fan.lock')
            child = ('import os,sys; print(os.getpid(), flush=True); '
                     'sys.stdin.read(1)')
            holder = subprocess.Popen(
                ['/usr/bin/flock', '--nonblock', '--no-fork', lock, 'python3', '-c', child],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                self.assertEqual(int(holder.stdout.readline().strip()), holder.pid)
                peer = subprocess.run(
                    ['/usr/bin/flock', '--nonblock', '--no-fork', lock, 'true'],
                    capture_output=True,
                )
                self.assertNotEqual(peer.returncode, 0)
            finally:
                holder.communicate(input='x', timeout=5)
            self.assertEqual(holder.returncode, 0)


if __name__ == '__main__':
    unittest.main()
