"""Deployment invariants for the production read-only Tradier collector."""
from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "workers" / "wrangler.tradier.json"
WORKER = ROOT / "workers" / "tradier_poller_v24_candidate.mjs"


class TradierWorkerDeploymentTests(unittest.TestCase):
    def test_config_pins_the_verified_production_identity_and_failover_trigger(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["name"], "options-tradier-paper-poller")
        self.assertEqual(config["main"], "tradier_poller_v24_candidate.mjs")
        self.assertEqual(config["compatibility_date"], "2026-10-24")
        self.assertEqual(config["triggers"]["crons"], ["* * * * *"])
        self.assertEqual(
            config["d1_databases"],
            [{
                "binding": "DB",
                "database_name": "options-research-tradier-private",
                "database_id": "07f6bd0d-a582-4244-be9f-d42e7c2d6d81",
            }],
        )
        # The token stays a Cloudflare secret. It must never be serialized in config.
        self.assertNotIn("TRADIER_TOKEN", CONFIG.read_text(encoding="utf-8"))

    def test_unrestricted_trigger_is_guarded_before_collection(self):
        source = WORKER.read_text(encoding="utf-8")
        self.assertIn("if(!isRegularSession(now))return 'market_closed';", source)
        self.assertIn("if (!isRegularSession(now)) return 'broad_market_closed';", source)
        self.assertIn("if(!isRegularSession(now))return 'option_market_closed';", source)
        self.assertIn("if(outcome==='market_closed'||outcome==='provider_cooldown')return;", source)
        self.assertIn("orders_enabled:false", source)
        for forbidden in (
            "/v1/accounts", "/orders", "placeOrder", "createOrder", "submitOrder"
        ):
            self.assertNotIn(forbidden, source)


    def test_protected_main_push_is_offline_and_scheduled_probe_stays_fail_closed(self):
        """Closed-market pushes run deterministic tests; scheduled/manual probes retain hard gates."""
        workflow = (ROOT / ".github/workflows/tradier-readonly-options.yml").read_text(encoding="utf-8")
        self.assertIn("  push:\n    branches: [main]", workflow)
        self.assertIn("    - cron: '13 15,17 * * 1-5'", workflow)
        def step(name):
            marker = "      - name: " + name + "\n"
            self.assertEqual(workflow.count(marker), 1, name)
            return workflow.split(marker, 1)[1].split("\n      - name: ", 1)[0]
        offline = step("Test read-only and fail-closed safeguards without credentials")
        self.assertIn("python -m unittest discover -v -s tests", offline)
        self.assertNotIn("if: github.event_name != 'push'", offline)
        for name in (
            "Probe 0DTE, 1DTE, and 7-21DTE Tradier chains (GET only)",
            "Require nonempty open-session Tradier option chains",
            "Cross-check option timestamps via option-specific quote GETs (diagnostic only)",
        ):
            live = step(name)
            self.assertIn("        if: github.event_name != 'push'\n", live, name)
        probe = step("Probe 0DTE, 1DTE, and 7-21DTE Tradier chains (GET only)")
        self.assertIn("python -m tradier_market_cycle", probe)
        self.assertIn("TRADIER_TOKEN:", probe)
        guard = step("Require nonempty open-session Tradier option chains")
        self.assertIn('result.get("market_state") == "open"', guard)
        self.assertIn("NO_VERIFIED_OPTION_CHAINS", guard)
        self.assertIn("chains_with_contracts", guard)
        quote = step("Cross-check option timestamps via option-specific quote GETs (diagnostic only)")
        self.assertIn("python -m tradier_greeks_crosscheck", quote)
        manual = step("Cross-check option Greek timestamps using separate GET endpoint (manual diagnostic only)")
        self.assertIn("github.event_name == 'workflow_dispatch'", manual)
        cleanup = step("Delete temporary market-data snapshot")
        self.assertIn("if: always()", cleanup)


if __name__ == "__main__":
    unittest.main()
