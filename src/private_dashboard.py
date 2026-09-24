from __future__ import annotations

import argparse
import html
import json
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

try:
    from case_evidence import RESEARCH_NOTICE, add_review, connect, export_case, verify_review_chain
except ImportError:  # package-style import
    from .case_evidence import RESEARCH_NOTICE, add_review, connect, export_case, verify_review_chain

SCHEMA_VERSION = "0.9.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
ALLOWED_ACTIONS = {
    "review_started",
    "note_added",
    "review_completed",
    "escalated_for_internal_review",
}
ALLOWED_DISPOSITIONS = {
    "pending_human_review",
    "under_review",
    "retained_for_monitoring",
    "closed_no_finding",
    "referred_for_internal_compliance_review",
}


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_pretty(value: str) -> str:
    try:
        return json.dumps(json.loads(value), indent=2, sort_keys=True)
    except Exception:
        return value


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


@dataclass(frozen=True)
class DashboardConfig:
    db_path: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    export_dir: Path | None = None

    def validate(self) -> None:
        if not _is_loopback_host(self.host):
            raise ValueError("private dashboard refuses non-loopback bind addresses")
        if not (0 <= int(self.port) <= 65535):
            raise ValueError("port must be in [0,65535]")
        if not self.db_path.exists():
            raise ValueError(f"case database does not exist: {self.db_path}")


class DashboardRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def list_cases(
        self,
        *,
        query: str = "",
        disposition: str = "",
        flagged: str = "",
        limit: int = 250,
    ) -> list[dict]:
        query = query.strip()
        disposition = disposition.strip()
        flagged = flagged.strip()
        clauses: list[str] = []
        params: list[object] = []
        if query:
            clauses.append("(c.case_id LIKE ? OR c.symbol LIKE ? OR c.event_id LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        if flagged in {"0", "1"}:
            clauses.append("c.flagged=?")
            params.append(int(flagged))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
        SELECT c.*,
               COALESCE((SELECT r.disposition FROM review_history r
                         WHERE r.case_id=c.case_id ORDER BY r.review_id DESC LIMIT 1),
                        c.initial_status) AS current_disposition,
               COALESCE((SELECT r.reviewed_at_utc FROM review_history r
                         WHERE r.case_id=c.case_id ORDER BY r.review_id DESC LIMIT 1),
                        c.created_at_utc) AS last_reviewed_at_utc,
               (SELECT COUNT(*) FROM review_history r WHERE r.case_id=c.case_id) AS review_count
        FROM case_record c
        {where}
        ORDER BY c.flagged DESC, c.surveillance_risk_score DESC, c.created_at_utc DESC
        LIMIT ?
        """
        params.append(int(limit))
        with connect(self.db_path) as con:
            rows = [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]
        if disposition:
            rows = [r for r in rows if str(r["current_disposition"]) == disposition]
        for row in rows:
            row["integrity_ok"] = self.case_integrity(row["case_id"])["ok"]
        return rows

    def case_integrity(self, case_id: str) -> dict:
        review_ok = verify_review_chain(self.db_path, case_id)
        with connect(self.db_path) as con:
            case = con.execute("SELECT * FROM case_record WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise KeyError(case_id)
            sources = [dict(r) for r in con.execute(
                "SELECT * FROM source_artifact WHERE case_id=? ORDER BY source_id", (case_id,)
            ).fetchall()]
            model_sources = [s for s in sources if s["artifact_role"] == "model_bundle"]
        hashes_well_formed = all(
            isinstance(s.get("sha256"), str) and len(s["sha256"]) == 64 for s in sources
        )
        model_hash_consistent = bool(model_sources) and all(
            s["sha256"] == case["model_sha256"] for s in model_sources
        )
        return {
            "review_chain_valid": review_ok,
            "source_hashes_well_formed": hashes_well_formed,
            "model_hash_consistent": model_hash_consistent,
            "source_count": len(sources),
            "ok": review_ok and hashes_well_formed and model_hash_consistent,
        }

    def case_detail(self, case_id: str) -> dict:
        with connect(self.db_path) as con:
            case = con.execute("SELECT * FROM case_record WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise KeyError(case_id)
            features = [dict(r) for r in con.execute(
                "SELECT * FROM feature_snapshot WHERE case_id=? ORDER BY ABS(CAST(feature_value AS REAL)) DESC, feature_name",
                (case_id,),
            ).fetchall()]
            controls = [dict(r) for r in con.execute(
                "SELECT * FROM control_snapshot WHERE case_id=? ORDER BY control_rank", (case_id,)
            ).fetchall()]
            timeline = [dict(r) for r in con.execute(
                "SELECT * FROM case_timeline WHERE case_id=? ORDER BY event_ts_utc, timeline_id", (case_id,)
            ).fetchall()]
            sources = [dict(r) for r in con.execute(
                "SELECT * FROM source_artifact WHERE case_id=? ORDER BY artifact_role, source_id", (case_id,)
            ).fetchall()]
            reviews = [dict(r) for r in con.execute(
                "SELECT * FROM review_history WHERE case_id=? ORDER BY review_id", (case_id,)
            ).fetchall()]
        case_d = dict(case)
        current_disposition = reviews[-1]["disposition"] if reviews else case_d["initial_status"]
        return {
            "case": case_d,
            "features": features,
            "controls": controls,
            "timeline": timeline,
            "sources": sources,
            "reviews": reviews,
            "current_disposition": current_disposition,
            "integrity": self.case_integrity(case_id),
        }


def _layout(title: str, body: str) -> bytes:
    css = """
    :root{font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#172033;background:#f5f7fa}
    *{box-sizing:border-box} body{margin:0;background:#f5f7fa} a{color:#2457a7;text-decoration:none} a:hover{text-decoration:underline}
    header{background:#111827;color:white;padding:18px 28px;display:flex;gap:24px;align-items:center;justify-content:space-between}
    header .sub{font-size:12px;color:#cbd5e1} main{max-width:1320px;margin:0 auto;padding:24px}
    .notice{background:#fff7ed;border:1px solid #fdba74;padding:12px 14px;border-radius:10px;margin:0 0 18px;font-size:13px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.card{background:white;border:1px solid #dbe1ea;border-radius:12px;padding:16px;box-shadow:0 1px 2px #00000008}
    .metric{font-size:27px;font-weight:700}.muted{color:#64748b;font-size:12px}.ok{color:#166534;font-weight:700}.bad{color:#b91c1c;font-weight:700}.warn{color:#9a3412;font-weight:700}
    table{width:100%;border-collapse:collapse;background:white;border:1px solid #dbe1ea;border-radius:10px;overflow:hidden} th,td{padding:9px 10px;border-bottom:1px solid #e7ebf0;text-align:left;font-size:13px;vertical-align:top} th{background:#f8fafc;font-weight:650} tr:last-child td{border-bottom:0}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#eef2ff;font-size:12px}.pill.flag{background:#fee2e2;color:#991b1b}.pill.good{background:#dcfce7;color:#166534}
    .section{margin-top:22px}.section h2{font-size:17px;margin:0 0 10px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.filters input,.filters select,.review-form input,.review-form select,.review-form textarea{padding:8px;border:1px solid #cbd5e1;border-radius:7px;background:white}.filters button,.review-form button,.button{padding:8px 12px;border:0;border-radius:7px;background:#1d4ed8;color:white;cursor:pointer}.button.secondary{background:#475569}
    pre{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#e2e8f0;padding:10px;border-radius:8px;font-size:12px;max-height:280px;overflow:auto}.review-form{display:grid;gap:10px;max-width:720px}.review-form textarea{min-height:90px}
    .hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all}.score{font-size:32px;font-weight:800}.back{margin-bottom:14px;display:inline-block}.two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}@media(max-width:850px){.two{grid-template-columns:1fr}}
    """
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_e(title)}</title><style>{css}</style></head><body><header><div><strong>Private Market-Surveillance Review</strong><div class='sub'>localhost-only · schema {SCHEMA_VERSION}</div></div><div class='sub'>No trading or execution outputs</div></header><main><div class='notice'>{_e(RESEARCH_NOTICE)}</div>{body}</main></body></html>"""
    return page.encode("utf-8")


def render_index(repo: DashboardRepository, params: dict[str, list[str]]) -> bytes:
    query = (params.get("q") or [""])[0]
    disposition = (params.get("disposition") or [""])[0]
    flagged = (params.get("flagged") or [""])[0]
    rows = repo.list_cases(query=query, disposition=disposition, flagged=flagged)
    total = len(rows)
    flagged_n = sum(int(r["flagged"]) for r in rows)
    integrity_n = sum(bool(r["integrity_ok"]) for r in rows)
    avg = sum(float(r["surveillance_risk_score"]) for r in rows) / total if total else 0
    body = f"""
    <div class='grid'>
      <div class='card'><div class='muted'>Visible cases</div><div class='metric'>{total}</div></div>
      <div class='card'><div class='muted'>Flagged for review</div><div class='metric'>{flagged_n}</div></div>
      <div class='card'><div class='muted'>Integrity verified</div><div class='metric'>{integrity_n}/{total}</div></div>
      <div class='card'><div class='muted'>Average surveillance score</div><div class='metric'>{avg:.1f}</div></div>
    </div>
    <div class='section'><form class='filters' method='get'>
      <input name='q' value='{_e(query)}' placeholder='case, symbol, event'>
      <select name='flagged'><option value=''>all flags</option><option value='1' {'selected' if flagged=='1' else ''}>flagged</option><option value='0' {'selected' if flagged=='0' else ''}>not flagged</option></select>
      <select name='disposition'><option value=''>all dispositions</option>{''.join(f"<option value='{_e(d)}' {'selected' if disposition==d else ''}>{_e(d)}</option>" for d in sorted(ALLOWED_DISPOSITIONS))}</select>
      <button type='submit'>Filter</button>
    </form>
    <table><thead><tr><th>Case</th><th>Security</th><th>Score</th><th>Flag</th><th>Disposition</th><th>Integrity</th><th>Created</th></tr></thead><tbody>
    {''.join(_case_row(r) for r in rows) if rows else "<tr><td colspan='7'>No cases match the current filters.</td></tr>"}
    </tbody></table></div>
    """
    return _layout("Private case dashboard", body)


def _case_row(r: dict) -> str:
    flag = "<span class='pill flag'>flagged</span>" if r["flagged"] else "<span class='pill'>not flagged</span>"
    integ = "<span class='ok'>verified</span>" if r["integrity_ok"] else "<span class='bad'>check</span>"
    return f"<tr><td><a href='/case/{urllib.parse.quote(str(r['case_id']))}'><strong>{_e(r['case_id'])}</strong></a><div class='muted'>{_e(r['event_id'])}</div></td><td>{_e(r['symbol'])}<div class='muted'>{_e(r['minute_ts_utc'])}</div></td><td>{float(r['surveillance_risk_score']):.1f}</td><td>{flag}</td><td>{_e(r['current_disposition'])}<div class='muted'>{int(r['review_count'])} review entries</div></td><td>{integ}</td><td>{_e(r['created_at_utc'])}</td></tr>"


def render_case(repo: DashboardRepository, case_id: str, csrf_token: str, flash: str = "") -> bytes:
    d = repo.case_detail(case_id)
    c = d["case"]
    integ = d["integrity"]
    integ_html = "<span class='ok'>VERIFIED</span>" if integ["ok"] else "<span class='bad'>CHECK REQUIRED</span>"
    flash_html = f"<div class='card ok'>{_e(flash)}</div>" if flash else ""
    body = f"""
      <a class='back' href='/'>← all cases</a>{flash_html}
      <div class='grid'>
        <div class='card'><div class='muted'>Case</div><div class='metric'>{_e(case_id)}</div><div>{_e(c['symbol'])} · {_e(c['minute_ts_utc'])}</div></div>
        <div class='card'><div class='muted'>Surveillance risk score</div><div class='score'>{float(c['surveillance_risk_score']):.1f}</div><div class='muted'>threshold {float(c['surveillance_threshold'])*100:.1f}/100 · {'flagged' if c['flagged'] else 'not flagged'}</div></div>
        <div class='card'><div class='muted'>Current disposition</div><div class='metric' style='font-size:19px'>{_e(d['current_disposition'])}</div></div>
        <div class='card'><div class='muted'>Evidence integrity</div><div class='metric' style='font-size:19px'>{integ_html}</div><div class='muted'>review chain: {integ['review_chain_valid']} · model hash: {integ['model_hash_consistent']}</div></div>
      </div>

      <div class='section two'>
        <div><h2>Feature explanation snapshot</h2><table><thead><tr><th>Feature</th><th>Value</th><th>Status</th></tr></thead><tbody>{''.join(f"<tr><td>{_e(x['feature_name'])}</td><td>{_e(x['feature_value'])}</td><td>{_e(x['feature_status'])}</td></tr>" for x in d['features']) or '<tr><td colspan=3>None</td></tr>'}</tbody></table></div>
        <div><h2>Matched controls</h2><table><thead><tr><th>Rank</th><th>Security</th><th>Score</th><th>Minute</th></tr></thead><tbody>{''.join(f"<tr><td>{_e(x['control_rank'])}</td><td>{_e(x['control_symbol'])}</td><td>{_e(x['control_risk_score'])}</td><td>{_e(x['minute_ts_utc'])}</td></tr>" for x in d['controls']) or '<tr><td colspan=4>None</td></tr>'}</tbody></table></div>
      </div>

      <div class='section'><h2>Timeline</h2><table><thead><tr><th>Time</th><th>Type</th><th>Subject</th><th>Detail</th></tr></thead><tbody>{''.join(f"<tr><td>{_e(x['event_ts_utc'])}</td><td>{_e(x['event_type'])}</td><td>{_e(x['subject_symbol'])}</td><td><pre>{_e(_json_pretty(x['detail_json']))}</pre></td></tr>" for x in d['timeline'])}</tbody></table></div>

      <div class='section two'>
        <div><h2>Source provenance</h2><table><thead><tr><th>Role</th><th>File</th><th>SHA-256</th></tr></thead><tbody>{''.join(f"<tr><td>{_e(x['artifact_role'])}</td><td>{_e(x['file_name'])}</td><td class='hash'>{_e(x['sha256'])}</td></tr>" for x in d['sources'])}</tbody></table></div>
        <div><h2>Integrity checks</h2><div class='card'><p>Review-chain valid: <strong>{_e(integ['review_chain_valid'])}</strong></p><p>Source hashes well formed: <strong>{_e(integ['source_hashes_well_formed'])}</strong></p><p>Model hash consistent: <strong>{_e(integ['model_hash_consistent'])}</strong></p><p>Recorded sources: <strong>{_e(integ['source_count'])}</strong></p><p>Overall: {integ_html}</p></div></div>
      </div>

      <div class='section'><h2>Review history</h2><table><thead><tr><th>#</th><th>Time</th><th>Reviewer</th><th>Action</th><th>Disposition</th><th>Note</th><th>Hash</th></tr></thead><tbody>{''.join(f"<tr><td>{_e(x['review_id'])}</td><td>{_e(x['reviewed_at_utc'])}</td><td>{_e(x['reviewer'])}</td><td>{_e(x['action'])}</td><td>{_e(x['disposition'])}</td><td>{_e(x['note'])}</td><td class='hash'>{_e(x['record_hash'])}</td></tr>" for x in d['reviews'])}</tbody></table></div>

      <div class='section two'>
        <div><h2>Add review entry</h2><form class='review-form' method='post' action='/case/{urllib.parse.quote(case_id)}/review'>
          <input type='hidden' name='csrf_token' value='{_e(csrf_token)}'>
          <input name='reviewer' required maxlength='100' value='owner' placeholder='reviewer'>
          <select name='action'>{''.join(f"<option value='{_e(x)}'>{_e(x)}</option>" for x in sorted(ALLOWED_ACTIONS))}</select>
          <select name='disposition'>{''.join(f"<option value='{_e(x)}'>{_e(x)}</option>" for x in sorted(ALLOWED_DISPOSITIONS))}</select>
          <textarea name='note' maxlength='4000' placeholder='review note (avoid conclusions unsupported by evidence)'></textarea>
          <button type='submit'>Append review record</button>
        </form></div>
        <div><h2>Evidence export</h2><div class='card'><p>Generate a reproducible evidence ZIP from the immutable case record. Raw licensed/proprietary sources remain outside the bundle.</p><form method='post' action='/case/{urllib.parse.quote(case_id)}/export'><input type='hidden' name='csrf_token' value='{_e(csrf_token)}'><button class='button secondary' type='submit'>Generate local evidence bundle</button></form></div></div>
      </div>
    """
    return _layout(f"Case {case_id}", body)


class PrivateDashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: DashboardConfig, csrf_token: str | None = None):
        config.validate()
        self.config = config
        self.repo = DashboardRepository(config.db_path)
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        super().__init__((config.host, config.port), _make_handler())


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server: PrivateDashboardServer

        def log_message(self, fmt: str, *args) -> None:
            # Local-only concise audit line; do not log form bodies or evidence details.
            super().log_message(fmt, *args)

        def _security_headers(self, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )

        def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self._security_headers(content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _host_header_is_local(self) -> bool:
            host = self.headers.get("Host", "")
            host_only = host.rsplit(":", 1)[0].strip("[]").lower() if host else ""
            return host_only in LOOPBACK_HOSTS

        def _parse_form(self) -> dict[str, str]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > 64_000:
                raise ValueError("invalid form size")
            body = self.rfile.read(length).decode("utf-8", "strict")
            parsed = urllib.parse.parse_qs(body, keep_blank_values=True, max_num_fields=20)
            return {k: v[-1] for k, v in parsed.items()}

        def _require_csrf(self, form: dict[str, str]) -> None:
            token = form.get("csrf_token", "")
            if not secrets.compare_digest(token, self.server.csrf_token):
                raise PermissionError("invalid CSRF token")

        def do_GET(self) -> None:
            if not self._host_header_is_local():
                self._send(HTTPStatus.FORBIDDEN, _layout("Forbidden", "<p>Non-loopback Host header rejected.</p>"))
                return
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/healthz":
                self._send(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8")
                return
            if parsed.path == "/":
                self._send(HTTPStatus.OK, render_index(self.server.repo, urllib.parse.parse_qs(parsed.query)))
                return
            if parsed.path.startswith("/case/"):
                case_id = urllib.parse.unquote(parsed.path[len("/case/"):]).strip("/")
                if "/" in case_id or not case_id:
                    self._send(HTTPStatus.NOT_FOUND, _layout("Not found", "<p>Unknown route.</p>"))
                    return
                try:
                    self._send(HTTPStatus.OK, render_case(self.server.repo, case_id, self.server.csrf_token))
                except KeyError:
                    self._send(HTTPStatus.NOT_FOUND, _layout("Not found", "<p>Case not found.</p>"))
                return
            self._send(HTTPStatus.NOT_FOUND, _layout("Not found", "<p>Unknown route.</p>"))

        def do_POST(self) -> None:
            if not self._host_header_is_local():
                self._send(HTTPStatus.FORBIDDEN, _layout("Forbidden", "<p>Non-loopback Host header rejected.</p>"))
                return
            parsed = urllib.parse.urlparse(self.path)
            try:
                form = self._parse_form()
                self._require_csrf(form)
            except PermissionError:
                self._send(HTTPStatus.FORBIDDEN, _layout("Forbidden", "<p>Invalid CSRF token.</p>"))
                return
            except Exception as exc:
                self._send(HTTPStatus.BAD_REQUEST, _layout("Bad request", f"<p>{_e(exc)}</p>"))
                return

            if parsed.path.startswith("/case/") and parsed.path.endswith("/review"):
                case_id = urllib.parse.unquote(parsed.path[len("/case/"):-len("/review")]).strip("/")
                action = form.get("action", "")
                disposition = form.get("disposition", "")
                if action not in ALLOWED_ACTIONS or disposition not in ALLOWED_DISPOSITIONS:
                    self._send(HTTPStatus.BAD_REQUEST, _layout("Bad request", "<p>Unsupported review action or disposition.</p>"))
                    return
                try:
                    add_review(
                        db_path=self.server.config.db_path,
                        case_id=case_id,
                        reviewer=form.get("reviewer", "")[:100],
                        action=action,
                        disposition=disposition,
                        note=form.get("note", "")[:4000],
                    )
                except Exception as exc:
                    self._send(HTTPStatus.BAD_REQUEST, _layout("Review failed", f"<p>{_e(exc)}</p>"))
                    return
                self._redirect(f"/case/{urllib.parse.quote(case_id)}")
                return

            if parsed.path.startswith("/case/") and parsed.path.endswith("/export"):
                case_id = urllib.parse.unquote(parsed.path[len("/case/"):-len("/export")]).strip("/")
                out_dir = self.server.config.export_dir or (self.server.config.db_path.parent / "dashboard_evidence")
                try:
                    result = export_case(db_path=self.server.config.db_path, case_id=case_id, output_dir=out_dir)
                    msg = f"Evidence bundle created locally: {result['zip_path']}"
                    self._send(HTTPStatus.OK, render_case(self.server.repo, case_id, self.server.csrf_token, msg))
                except Exception as exc:
                    self._send(HTTPStatus.BAD_REQUEST, _layout("Export failed", f"<p>{_e(exc)}</p>"))
                return

            self._send(HTTPStatus.NOT_FOUND, _layout("Not found", "<p>Unknown route.</p>"))

    return Handler


def serve(config: DashboardConfig, *, open_browser: bool = False) -> None:
    server = PrivateDashboardServer(config)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Private dashboard: {url}")
    print("Bound to loopback only. Press Ctrl-C to stop.")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-only private surveillance case dashboard")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--export-dir", type=Path)
    p.add_argument("--open-browser", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg = DashboardConfig(args.db, args.host, args.port, args.export_dir)
    serve(cfg, open_browser=args.open_browser)


if __name__ == "__main__":
    main()
