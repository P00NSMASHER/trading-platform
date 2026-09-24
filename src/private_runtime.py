from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from deployment_hardening import apply_private_permissions, load_runtime_config, self_check
    from private_dashboard import DashboardConfig, serve
except ImportError:  # package-style import
    from .deployment_hardening import apply_private_permissions, load_runtime_config, self_check
    from .private_dashboard import DashboardConfig, serve


def main() -> None:
    p = argparse.ArgumentParser(description="Fail-closed private surveillance runtime launcher")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--open-browser", action="store_true")
    args = p.parse_args()

    cfg = load_runtime_config(args.config)
    permission_result = apply_private_permissions(cfg)
    if not permission_result.get("ok"):
        raise SystemExit("unable to enforce private filesystem permissions")
    report = self_check(cfg)
    cfg.audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = cfg.audit_dir / "startup_self_check.json"
    audit_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report.get("ok"):
        raise SystemExit(f"startup self-check failed; see {audit_path}")

    serve(
        DashboardConfig(
            db_path=cfg.case_db,
            host=cfg.dashboard_host,
            port=cfg.dashboard_port,
            export_dir=cfg.export_dir,
        ),
        open_browser=args.open_browser,
    )


if __name__ == "__main__":
    main()
