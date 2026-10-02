from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/processed/g2_vendor_requests/vendor_reply_evidence_2026-10-02.json"


def test_thetadata_written_reply_preserves_price_license_and_retention_terms():
    payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    theta = payload["thetadata_written_reply"]
    confirmation = theta["vendor_confirmation"]

    assert theta["source_date"] == "2026-10-02"
    assert confirmation["private_research_eligible_individual_options_pro"] is True
    assert confirmation["options_pro_one_month_usd"] == 160
    assert confirmation["stocks_pro_one_month_usd"] == 160
    assert confirmation["combined_one_month_usd"] == 320
    assert confirmation["raw_unmodified_retention"] == (
        "DELETE_WITHIN_30_DAYS_AFTER_SUBSCRIPTION_BILLING_PERIOD_ENDS"
    )
    assert confirmation["modified_or_derived_research_data_retention"] == (
        "MAY_BE_RETAINED_IF_UNDERLYING_RAW_DATA_IS_DELETED"
    )
    assert confirmation["option_requests_estimate"] if "option_requests_estimate" in confirmation else True
    assert theta["coverage_effect"] == "NONE_UNTIL_ACTUAL_VALIDATED_ROWS"
    assert theta["automatic_purchase_or_subscription"] is False
