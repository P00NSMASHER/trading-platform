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


if __name__ == "__main__":
    unittest.main()
