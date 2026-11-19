#!/usr/bin/env python3
import os
import subprocess
import unittest
from pathlib import Path

BOOTSTRAP = Path(__file__).resolve().parents[1] / "bootstrap.sh"
SCRIPT = BOOTSTRAP.read_text()
START = SCRIPT.index("upgrade_ubuntu() {")
END = SCRIPT.index("\nupgrade_ubuntu /etc/os-release", START)
FUNCTION = SCRIPT[START:END]
MOCKS = r"""
MOCK_CURRENT=${MOCK_CURRENT:-26.04}
MOCK_STABLE=${MOCK_STABLE:-26.10}
MOCK_NORMAL=${MOCK_NORMAL:-none}
MOCK_DEVEL=${MOCK_DEVEL:-26.10}
MOCK_POLICY=${MOCK_POLICY:-normal}
TRACE=''

grep() {
	case "$1" in
		-c) printf '%s\n' "${MOCK_POLICY_COUNT:-1}" ;;
		-qx) [[ $MOCK_POLICY == normal ]] ;;
		*) return 1 ;;
	esac
}

source() {
	ID=ubuntu
	VERSION_ID=$MOCK_CURRENT
}

ubuntu-distro-info() {
	if [[ $* == *--release* ]]; then
		printf '%s\n' "$MOCK_STABLE"
	else
		printf '%s\n' stable-codename
	fi
}

do-release-upgrade() {
	local result=$MOCK_NORMAL
	if [[ $* == *--devel-release* ]]; then
		result=$MOCK_DEVEL
	fi
	if [[ $result == multi ]]; then
		if [[ $MOCK_CURRENT == 24.04 ]]; then result=26.04; else result=none; fi
	fi
	case "$result" in
		none) printf 'No new release found.\n'; return 1 ;;
		error) printf 'Network error\n'; return 1 ;;
		*) printf "New release '%s' available.\n" "$result" ;;
	esac
}

sudo() {
	TRACE+=" $*;"
	case "$1" in
		sed) MOCK_POLICY=normal ;;
		apt-get) [[ ${MOCK_APT_FAIL:-0} != 1 ]] ;;
		do-release-upgrade)
			[[ ${MOCK_UPGRADE_FAIL:-0} != 1 ]] || return 1
			if [[ ${MOCK_NO_CHANGE:-0} != 1 ]]; then
				if [[ $MOCK_CURRENT == 24.04 ]]; then
					MOCK_CURRENT=26.04
				else
					MOCK_CURRENT=${MOCK_AFTER:-26.10}
				fi
			fi
			;;
		*) return 1 ;;
	esac
}
"""


def run_scenario(**variables):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in variables.items()})
    script = (
        MOCKS
        + "\n"
        + FUNCTION
        + r"""
upgrade_ubuntu release-file policy-file
result=$?
if [[ ${MOCK_TWICE:-0} == 1 && $result == 0 ]]; then
	upgrade_ubuntu release-file policy-file
	result=$?
fi
printf '\nRESULT=%s CURRENT=%s TRACE=%s\n' "$result" "$MOCK_CURRENT" "$TRACE"
exit "$result"
"""
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class BootstrapReleaseTests(unittest.TestCase):
    def test_already_stable_does_not_run_release_upgrader(self):
        result = run_scenario(MOCK_CURRENT="26.10", MOCK_TWICE=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("sudo do-release-upgrade", result.stdout)
        self.assertNotIn("do-release-upgrade --", result.stdout)
        self.assertEqual(result.stdout.count("apt-get dist-upgrade -y"), 2)

    def test_released_development_feed_fallback_runs_once(self):
        result = run_scenario(MOCK_TWICE=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("do-release-upgrade --devel-release"), 1)
        self.assertIn("CURRENT=26.10", result.stdout)

    def test_normal_feed_is_preferred(self):
        result = run_scenario(MOCK_NORMAL="26.10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("do-release-upgrade -f DistUpgradeViewNonInteractive", result.stdout)
        self.assertNotIn("do-release-upgrade --devel-release", result.stdout)

    def test_lts_point_release_is_parsed(self):
        result = run_scenario(MOCK_CURRENT="24.04", MOCK_NORMAL="26.04.1 LTS", MOCK_STABLE="26.04", MOCK_AFTER="26.04")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CURRENT=26.04", result.stdout)

    def test_sequential_stable_upgrades(self):
        result = run_scenario(MOCK_CURRENT="24.04", MOCK_NORMAL="multi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("do-release-upgrade "), 2)
        self.assertIn("CURRENT=26.10", result.stdout)

    def test_rejects_future_development_release(self):
        result = run_scenario(MOCK_DEVEL="27.04")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing offered release", result.stderr)
        self.assertNotIn("do-release-upgrade --devel-release", result.stdout)

    def test_rejects_nonlatest_development_feed_candidate(self):
        result = run_scenario(MOCK_CURRENT="24.04", MOCK_DEVEL="26.04")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing offered release", result.stderr)

    def test_normal_check_error_does_not_fall_back(self):
        result = run_scenario(MOCK_NORMAL="error")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Normal release check failed", result.stderr)
        self.assertNotIn("do-release-upgrade --devel-release", result.stdout)

    def test_package_failure_stops_bootstrap(self):
        result = run_scenario(MOCK_APT_FAIL=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("do-release-upgrade --devel-release", result.stdout)

    def test_failed_release_upgrade_stops_bootstrap(self):
        result = run_scenario(MOCK_UPGRADE_FAIL=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CURRENT=26.04", result.stdout)

    def test_release_must_match_checked_candidate(self):
        result = run_scenario(MOCK_NO_CHANGE=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not reach the checked version", result.stderr)

    def test_policy_is_changed_only_when_needed(self):
        result = run_scenario(MOCK_CURRENT="26.10", MOCK_POLICY="lts", MOCK_TWICE=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("sed -i"), 1)

    def test_ambiguous_policy_is_rejected(self):
        result = run_scenario(MOCK_POLICY_COUNT=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected exactly one Prompt setting", result.stderr)
        self.assertNotIn("apt-get", result.stdout)

    def test_newer_current_version_is_not_downgraded(self):
        result = run_scenario(MOCK_CURRENT="27.04")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("newer than the known stable release", result.stderr)
        self.assertNotIn("do-release-upgrade --devel-release", result.stdout)


if __name__ == "__main__":
    unittest.main()
