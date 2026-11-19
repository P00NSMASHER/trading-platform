"""Run the isolated one-minute Tradier collector regression against the real JS module.

All provider responses and D1 writes in the Node fixture are synthetic; no network
or production credentials are required.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests" / "tradier_underlying_minute_integrity.test.mjs"


class TradierUnderlyingMinuteIntegrityTests(unittest.TestCase):
    def test_real_worker_module_isolates_underlying_minutes_on_later_failures(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable; GitHub pr-ci provisions Node 24")
        result = subprocess.run(
            [node, "--test", str(NODE_TEST)],
            cwd=ROOT, capture_output=True, text=True, timeout=35, check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            "Worker timing/retention regression failed:\n"
            + result.stdout[-6000:] + "\n" + result.stderr[-6000:],
        )


if __name__ == "__main__":
    unittest.main()
