from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")


def test_dashboard_loads_machine_readable_readiness_receipts():
    assert "../data/processed/software_readiness/software_readiness_certification.json" in HTML
    assert "../data/processed/real_data_replay/real_data_replay_status.json" in HTML
    assert 'cache: "no-store"' in HTML
    assert 'id="g2CoverageValue"' in HTML
    assert 'id="evaluationValue"' in HTML
    assert 'id="hostileTestValue"' in HTML
    assert 'id="replayProofValue"' in HTML


def test_dashboard_retains_fail_closed_static_fallback():
    assert "0 / 1,656" in HTML
    assert "BLOCKED" in HTML
    assert "static snapshot fallback" in HTML
    assert "live certification receipt unavailable" in HTML


def test_dashboard_does_not_embed_private_vendor_secrets():
    lower = HTML.lower()
    for forbidden in (
        "api_key=",
        "api-key=",
        "password=",
        "private_key",
        "authorization: bearer",
        "sftp_password",
    ):
        assert forbidden not in lower
