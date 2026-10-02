from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/g2-databento-cost-probe.yml"


def test_databento_cost_probe_workflow_is_main_push_only_and_non_purchase():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "pull_request:" not in text
    assert "workflow_dispatch:" not in text
    assert "permissions:\n  contents: read" in text

    assert "secrets.DATABENTO_API_KEY" in text
    assert "--estimate-costs" in text
    assert "--budget-usd 125" in text
    assert "metadata.get_cost" not in text  # delegated to the reviewed probe utility
    assert "timeseries.get_range" not in text
    assert "batch" not in text.lower()
    assert "purchase" not in text.lower()
    assert "add to cart" not in text.lower()


def test_databento_cost_probe_workflow_fails_closed_without_key():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "DATABENTO_API_KEY_NOT_CONFIGURED" in text
    assert "steps.key.outputs.configured == 'true'" in text
    assert "persist-credentials: false" in text
