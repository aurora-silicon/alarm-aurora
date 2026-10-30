"""Run package lifecycle scriptlets against a stateful systemctl double."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FexOverlayTests(unittest.TestCase):
    def run_lifecycle(self, active=True, stop_fails=False, start_fails=False, stale_mount=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            if active:
                (root / 'active').touch()
                (root / 'mounted').touch()
            if stale_mount:
                (root / 'mounted').touch()
            ctl = root / 'systemctl'
            ctl.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$TEST_ROOT/log"
case "$*" in
  *is-active*) test -e "$TEST_ROOT/active" ;;
  stop*) test "$STOP_FAILS" = no || exit 1; rm -f "$TEST_ROOT/active" "$TEST_ROOT/mounted" ;;
  start*) test "$START_FAILS" = no || exit 1; touch "$TEST_ROOT/active" ;;
  *) exit 0 ;;
esac
""")
            ctl.chmod(0o755)
            mountpoint = root / 'mountpoint'
            mountpoint.write_text('#!/bin/bash\ntest -e "$TEST_ROOT/mounted"\n')
            mountpoint.chmod(0o755)
            script = self.script().replace('/run/systemd/system', str(root / 'system')).replace('/run/aurora-fex-mesa.upgrade', str(root / 'marker'))
            env = dict(os.environ, PATH=tmp + ':' + os.environ['PATH'], TEST_ROOT=tmp,
                       STOP_FAILS='yes' if stop_fails else 'no', START_FAILS='yes' if start_fails else 'no')
            pre = subprocess.run(['bash', '-c', script + '\n' + self.pre()], env=env)
            if (stop_fails and active) or stale_mount:
                self.assertNotEqual(pre.returncode, 0)
                self.assertEqual((root / 'active').exists(), active)
                self.assertFalse((root / 'marker').exists())
                return
            self.assertEqual(pre.returncode, 0)
            self.assertFalse((root / 'active').exists())
            self.assertEqual((root / 'marker').exists(), active)
            post = subprocess.run(['bash', '-c', script + '\n' + self.post()], env=env)
            self.assertEqual((root / 'active').exists(), active and not start_fails)
            self.assertEqual((root / 'marker').exists(), active and start_fails)
            self.assertEqual(post.returncode == 0, not (active and start_fails))

    def test_running_service_is_stopped_and_restored(self):
        self.run_lifecycle()

    def test_inactive_service_stays_inactive(self):
        self.run_lifecycle(active=False)

    def test_failed_stop_is_reported_before_unpack(self):
        self.run_lifecycle(stop_fails=True)

    def test_stale_mount_is_reported_before_unpack(self):
        self.run_lifecycle(active=False, stale_mount=True)

    def test_failed_remount_retains_recovery_marker(self):
        self.run_lifecycle(start_fails=True)

    def script(self):
        return (ROOT / 'packages/mesa-aurora-fex-guest/mesa-aurora-fex-guest.install').read_text()

    def pre(self):
        return 'pre_upgrade 2 1'

    def post(self):
        return 'post_upgrade 2 1'
