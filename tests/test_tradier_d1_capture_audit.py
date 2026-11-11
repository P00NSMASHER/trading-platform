"""Offline, secret-free regression cases for private D1 capture status."""
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import tradier_d1_capture_audit as audit

DAY = date(2026, 11, 10)
AS_OF = datetime(2026, 11, 10, 21, 4, tzinfo=timezone.utc)


def record(minute):
    return {"observed_minute": minute, "state": "captured_2_stocks_24_options",
            "underlyings_expected": 2, "underlyings_valid": 2,
            "options_planned": 24, "options_valid": 24, "options_aligned": 24,
            "quotes_accepted": 26, "coverage_state": "complete_verified_option_snapshot"}


def full_day():
    a, b = audit.regular_window(DAY, AS_OF)
    return [record(minute) for minute in audit.expected_minutes(a, b)]


class ReadOnlyCaptureAuditTests(unittest.TestCase):
    def test_390_390_live_coverage_is_complete_but_not_a_profit_or_current_connectivity_claim(self):
        report = audit.assess(full_day(), DAY, AS_OF, origin="offline_fixture")
        self.assertEqual(report["capture_status"], "COMPLETE_CAPTURE_OBSERVED")
        self.assertEqual((report["expected_minutes"], report["observed_minutes"], report["complete_minutes"]), (390,390,390))
        self.assertEqual(report["window_start_utc"], "2026-11-10T14:30:00Z")
        self.assertEqual(report["window_end_exclusive_utc"], "2026-11-10T21:00:00Z")
        self.assertEqual(report["provider_connectivity_now"], "UNVERIFIED")
        self.assertEqual(report["profitable_strategy"], "UNVERIFIED")
        self.assertEqual(report["evidence_origin"], "offline_fixture")

    def test_github_delayed_postmarket_failure_does_not_override_live_collector_receipts(self):
        passed = audit.assess(full_day(), DAY, AS_OF, github_diagnostic="success")
        delayed = audit.assess(full_day(), DAY, AS_OF, github_diagnostic="delayed_postmarket")
        self.assertEqual(passed["capture_status"], delayed["capture_status"])
        self.assertEqual(delayed["github_diagnostic"], "delayed_postmarket")
        self.assertFalse(delayed["github_diagnostic_changes_capture_status"])

    def test_missing_and_partial_are_not_labeled_provider_outage(self):
        rows = full_day()
        rows.pop(42)
        rows[20]["options_valid"] = 20
        report = audit.assess(rows, DAY, AS_OF)
        self.assertEqual(report["capture_status"], "INCOMPLETE_CAPTURE_OBSERVED")
        self.assertEqual((report["missing_minutes"],report["partial_minutes"],report["complete_minutes"]), (1,1,388))
        self.assertEqual(report["provider_connectivity_now"], "UNVERIFIED")
        none = audit.assess([], DAY, AS_OF)
        self.assertEqual(none["capture_status"], "NO_CAPTURE_RECORDS")
        self.assertNotEqual(none["capture_status"], "PROVIDER_OFFLINE")

    def test_inconsistent_receipt_is_never_counted_as_complete(self):
        rows = full_day()
        for key, value in (("underlyings_valid",True),("options_planned",0),("quotes_accepted",1)):
            sample = dict(rows[0]); sample[key] = value
            r = audit.assess([sample]+rows[1:], DAY, AS_OF)
            self.assertEqual(r["partial_minutes"], 1)
            self.assertNotEqual(r["capture_status"], "COMPLETE_CAPTURE_OBSERVED")

    def test_repeated_or_unaligned_minute_fails_closed(self):
        rows = full_day()
        rows.append(dict(rows[0]))
        a = audit.assess(rows, DAY, AS_OF)
        self.assertEqual(a["capture_status"], "INVALID_EVIDENCE")
        rows = full_day()
        rows[0]["observed_minute"] = "2026-11-10T14:30:20Z"
        self.assertEqual(audit.assess(rows, DAY, AS_OF)["capture_status"], "INVALID_EVIDENCE")

    def test_inprogress_window_uses_two_minute_grace_and_does_not_require_future_records(self):
        as_of = datetime(2026,11,10,15,2,tzinfo=timezone.utc)  # 10:02 ET
        start,end = audit.regular_window(DAY, as_of)
        self.assertEqual(len(audit.expected_minutes(start,end)),30)
        rows = [record(m) for m in audit.expected_minutes(start,end)]
        self.assertEqual(audit.assess(rows, DAY, as_of)["capture_status"], "COMPLETE_CAPTURE_OBSERVED")

    def test_dst_boundary_is_eastern_not_fixed_utc(self):
        summer = date(2026,7,6)
        as_of = datetime(2026,7,6,21,3,tzinfo=timezone.utc)
        start,end = audit.regular_window(summer,as_of)
        self.assertEqual(audit.utc_iso(start),"2026-07-06T13:30:00Z")
        self.assertEqual(audit.utc_iso(end),"2026-07-06T20:00:00Z")
        with self.assertRaisesRegex(audit.AuditError,"weekend"):
            audit.regular_window(date(2026,11,8),AS_OF)

    def test_d1_request_is_single_bounded_select_and_never_uses_brokerage(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self,n):
                return json.dumps({"success":True,"result":[{"results":[record("2026-11-10T14:30:00Z")]}]}).encode()
        class Transport:
            def open(self,req,timeout):
                self.req=req
                self.timeout=timeout
                return Response()
        t=Transport()
        start,end=audit.regular_window(DAY,AS_OF)
        got=audit.cloudflare_rows(start,end,account="a"*32,database="1"*8+"-"+"2"*4+"-"+"3"*4+"-"+"4"*4+"-"+"5"*12,token="TEST_ONLY",opener=t)
        self.assertEqual(len(got),1)
        self.assertEqual(t.req.get_method(),"POST")
        self.assertEqual(t.timeout,15)
        self.assertTrue(t.req.full_url.startswith("https://api.cloudflare.com/client/v4/accounts/"))
        body=json.loads(t.req.data)
        self.assertTrue(body["sql"].startswith("SELECT "))
        self.assertIn("LIMIT 391",body["sql"])
        self.assertEqual(body["params"], ["2026-11-10T14:30:00.000Z", "2026-11-10T21:00:00.000Z"])
        self.assertNotIn("SELECT *",body["sql"])
        self.assertNotIn("INSERT",body["sql"])
        self.assertNotIn("/accounts/", body["sql"])
        self.assertNotIn("/orders", body["sql"])

    def test_cloudflare_unavailable_is_unverified_not_no_connection(self):
        class Transport:
            def open(self,req,timeout):
                raise HTTPError(req.full_url,403,"sensitive provider detail",{},None)
        start,end=audit.regular_window(DAY,AS_OF)
        with self.assertRaisesRegex(audit.AuditError,"Cloudflare_D1_HTTP_403") as result:
            audit.cloudflare_rows(start,end,account="a"*32,database="1"*8+"-"+"2"*4+"-"+"3"*4+"-"+"4"*4+"-"+"5"*12,token="TEST_ONLY",opener=Transport())
        self.assertNotIn("sensitive provider detail",str(result.exception))

    def test_malformed_d1_response_fails_closed(self):
        bads=[{}, {"success":False,"errors":[{"message":"secret"}]}, {"success":True,"result":[]},
              {"success":True,"result":[{"results":{}}]},
              {"success":True,"result":[{"success":False,"results":[]}]}]
        for payload in bads:
            with self.assertRaises(audit.AuditError):
                audit.parse_d1_response(payload)


if __name__ == "__main__":
    unittest.main()
